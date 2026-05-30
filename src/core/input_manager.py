from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pygame

try:
    from pygame._sdl2 import controller as sdl_controller
except ImportError:  # pragma: no cover
    sdl_controller = None


@dataclass(frozen=True)
class InputConfig:
    stick_deadzone: float = 0.20
    stick_release_deadzone: float = 0.10
    stick_direction_threshold: float = 0.12
    stick_repeat_initial_s: float = 0.20
    stick_repeat_interval_s: float = 0.09


class InputManager:
    def __init__(self, config: InputConfig | None = None) -> None:
        self.config = config or InputConfig()
        self._controllers: dict[int, Any] = {}
        self._joysticks: dict[int, pygame.joystick.Joystick] = {}
        self._synthetic_actions: list[str] = []
        self._prev_lb = False
        self._prev_rb = False
        self._prev_start = False
        self._using_controller = False
        self._stick_engaged = False
        self._stick_digital: tuple[int, int] = (0, 0)
        self._stick_hold_s = 0.0
        self._stick_repeat_timer = 0.0

    @property
    def mouse_enabled(self) -> bool:
        return not self._using_controller

    @property
    def using_controller(self) -> bool:
        return self._using_controller

    def has_controllers(self) -> bool:
        return bool(self._controllers or self._joysticks)

    def initialize(self) -> None:
        pygame.joystick.init()
        if sdl_controller is not None:
            sdl_controller.init()
            for idx in range(sdl_controller.get_count()):
                self._try_add_controller(idx)
        if not self._controllers:
            self._refresh_joysticks()

    def update(self, dt: float) -> None:
        self._synthetic_actions.clear()
        if not self.has_controllers():
            self._prev_lb = False
            self._prev_rb = False
            self._prev_start = False
            self._reset_stick_navigation()
            return

        lb_pressed, rb_pressed, start_pressed = self._aggregate_controller_state()
        exit_combo = lb_pressed and rb_pressed and start_pressed
        exit_combo_prev = self._prev_lb and self._prev_rb and self._prev_start

        if exit_combo and not exit_combo_prev:
            self._synthetic_actions.append("EXIT_TO_DESKTOP")
        elif not exit_combo and not start_pressed:
            if lb_pressed and not self._prev_lb:
                self._mark_controller_active()
                self._synthetic_actions.append("HUB_PREV")
            if rb_pressed and not self._prev_rb:
                self._mark_controller_active()
                self._synthetic_actions.append("HUB_NEXT")

        self._prev_lb = lb_pressed
        self._prev_rb = rb_pressed
        self._prev_start = start_pressed

        self._poll_stick_navigation(dt)

    def consume_synthetic_actions(self) -> list[str]:
        out = list(self._synthetic_actions)
        self._synthetic_actions.clear()
        return out

    def handle_device_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.CONTROLLERDEVICEADDED:
            if sdl_controller is not None:
                self._try_add_controller(event.device_index)
                if self._controllers:
                    self._joysticks.clear()
        elif event.type == pygame.CONTROLLERDEVICEREMOVED:
            self._controllers.pop(event.instance_id, None)
            if not self._controllers:
                self._refresh_joysticks()
            if not self.has_controllers():
                self._using_controller = False
                self._reset_stick_navigation()
        elif event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
            if not self._controllers:
                self._refresh_joysticks()
            if not self.has_controllers():
                self._using_controller = False
                self._reset_stick_navigation()

    def _refresh_joysticks(self) -> None:
        self._joysticks.clear()
        for idx in range(pygame.joystick.get_count()):
            stick = pygame.joystick.Joystick(idx)
            if not stick.get_init():
                stick.init()
            self._joysticks[idx] = stick

    def _reset_stick_navigation(self) -> None:
        self._stick_engaged = False
        self._stick_digital = (0, 0)
        self._stick_hold_s = 0.0
        self._stick_repeat_timer = 0.0

    def _mark_controller_active(self) -> None:
        self._using_controller = True

    def _mark_mouse_active(self) -> None:
        self._using_controller = False

    def actions_from_event(self, event: pygame.event.Event) -> list[str]:
        actions: list[str] = []
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_a):
                actions.append("MOVE_LEFT")
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                actions.append("MOVE_RIGHT")
            elif event.key in (pygame.K_UP, pygame.K_w):
                actions.append("MOVE_UP")
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                actions.append("MOVE_DOWN")
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                actions.append("SELECT")
            elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                actions.append("BACK")
            elif event.key == pygame.K_x:
                actions.append("DETAILS")

        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            if self._using_controller:
                self._mark_mouse_active()

        if event.type == pygame.MOUSEMOTION:
            x, y = event.pos
            actions.append(f"MOUSE_HOVER:{x}:{y}")

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            x, y = event.pos
            actions.append(f"MOUSE_CLICK:{x}:{y}")

        if event.type == pygame.CONTROLLERBUTTONDOWN:
            self._mark_controller_active()
            if event.button == pygame.CONTROLLER_BUTTON_A:
                actions.append("SELECT")
            elif event.button == pygame.CONTROLLER_BUTTON_B:
                actions.append("BACK")
            elif event.button == pygame.CONTROLLER_BUTTON_DPAD_LEFT:
                actions.append("MOVE_LEFT")
            elif event.button == pygame.CONTROLLER_BUTTON_DPAD_RIGHT:
                actions.append("MOVE_RIGHT")
            elif event.button == pygame.CONTROLLER_BUTTON_DPAD_UP:
                actions.append("MOVE_UP")
            elif event.button == pygame.CONTROLLER_BUTTON_DPAD_DOWN:
                actions.append("MOVE_DOWN")
            elif event.button == pygame.CONTROLLER_BUTTON_X:
                actions.append("DETAILS")
            elif event.button == pygame.CONTROLLER_BUTTON_Y:
                actions.append("GUIDE_Y")
            elif event.button == getattr(pygame, "CONTROLLER_BUTTON_GUIDE", 16):
                actions.append("TOGGLE_GUIDE")

        if event.type in (pygame.CONTROLLERAXISMOTION, pygame.JOYAXISMOTION):
            self._mark_controller_active()

        if event.type == pygame.JOYBUTTONDOWN:
            self._mark_controller_active()

        return actions

    def _poll_stick_navigation(self, dt: float) -> None:
        x, y = self._left_stick_normalized()
        magnitude = max(abs(x), abs(y))
        cfg = self.config

        if magnitude < cfg.stick_release_deadzone:
            self._reset_stick_navigation()
            return

        if not self._stick_engaged:
            if magnitude < cfg.stick_deadzone:
                return
            digital = self._stick_to_digital(x, y)
            if digital == (0, 0):
                return
            action = self._action_for_stick_digital(digital)
            if action is None:
                return
            self._mark_controller_active()
            self._stick_engaged = True
            self._stick_digital = digital
            self._stick_hold_s = 0.0
            self._stick_repeat_timer = 0.0
            self._synthetic_actions.append(action)
            return

        action = self._action_for_stick_digital(self._stick_digital)
        if action is None:
            return

        self._mark_controller_active()
        self._stick_hold_s += dt
        self._stick_repeat_timer = max(0.0, self._stick_repeat_timer - dt)
        if (
            self._stick_hold_s >= cfg.stick_repeat_initial_s
            and self._stick_repeat_timer <= 0.0
        ):
            self._stick_repeat_timer = cfg.stick_repeat_interval_s
            self._synthetic_actions.append(action)

    @staticmethod
    def _normalize_axis(value: float) -> float:
        if abs(value) > 1.0:
            return max(-1.0, min(1.0, value / 32767.0))
        return max(-1.0, min(1.0, value))

    def _left_stick_normalized(self) -> tuple[float, float]:
        if self._controllers:
            sx = 0.0
            sy = 0.0
            count = 0
            for ctl in self._controllers.values():
                sx += self._normalize_axis(float(ctl.get_axis(pygame.CONTROLLER_AXIS_LEFTX)))
                sy += self._normalize_axis(float(ctl.get_axis(pygame.CONTROLLER_AXIS_LEFTY)))
                count += 1
            return sx / count, sy / count

        for stick in self._joysticks.values():
            if stick.get_numaxes() < 2:
                continue
            return (
                self._normalize_axis(float(stick.get_axis(0))),
                self._normalize_axis(float(stick.get_axis(1))),
            )
        return 0.0, 0.0

    def _stick_to_digital(self, x: float, y: float) -> tuple[int, int]:
        dz = self.config.stick_direction_threshold
        ax = abs(x)
        ay = abs(y)
        if ax < dz and ay < dz:
            return (0, 0)
        if ax >= ay:
            return (1 if x > 0 else -1, 0)
        return (0, 1 if y > 0 else -1)

    @staticmethod
    def _action_for_stick_digital(digital: tuple[int, int]) -> str | None:
        dx, dy = digital
        if dx > 0:
            return "MOVE_RIGHT"
        if dx < 0:
            return "MOVE_LEFT"
        if dy > 0:
            return "MOVE_DOWN"
        if dy < 0:
            return "MOVE_UP"
        return None

    def _try_add_controller(self, device_index: int) -> None:
        if sdl_controller is None or not sdl_controller.is_controller(device_index):
            return
        controller = sdl_controller.Controller(device_index)
        self._controllers[controller.as_joystick().get_instance_id()] = controller
        self._joysticks.clear()

    def _aggregate_controller_state(self) -> tuple[bool, bool, bool]:
        lb = False
        rb = False
        start = False
        for ctl in self._controllers.values():
            if ctl.get_button(pygame.CONTROLLER_BUTTON_LEFTSHOULDER):
                lb = True
            if ctl.get_button(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER):
                rb = True
            if ctl.get_button(pygame.CONTROLLER_BUTTON_START):
                start = True
            if lb and rb and start:
                break
        return lb, rb, start
