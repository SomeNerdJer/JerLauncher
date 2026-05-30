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
    stick_deadzone: float = 0.35
    repeat_cooldown_s: float = 0.16


class InputManager:
    def __init__(self, config: InputConfig | None = None) -> None:
        self.config = config or InputConfig()
        self._controllers: dict[int, Any] = {}
        self._cooldown = 0.0
        self._synthetic_actions: list[str] = []
        self._prev_lb = False
        self._prev_rb = False
        self._prev_start = False

    def initialize(self) -> None:
        pygame.joystick.init()
        if sdl_controller is None:
            return
        sdl_controller.init()
        for idx in range(sdl_controller.get_count()):
            self._try_add_controller(idx)

    def update(self, dt: float) -> None:
        self._cooldown = max(0.0, self._cooldown - dt)
        self._synthetic_actions.clear()
        if not self._controllers:
            self._prev_lb = False
            self._prev_rb = False
            self._prev_start = False
            return

        lb_pressed, rb_pressed, start_pressed = self._aggregate_controller_state()
        exit_combo = lb_pressed and rb_pressed and start_pressed
        exit_combo_prev = self._prev_lb and self._prev_rb and self._prev_start

        if exit_combo and not exit_combo_prev:
            self._synthetic_actions.append("EXIT_TO_DESKTOP")
        elif not exit_combo and not start_pressed:
            if lb_pressed and not self._prev_lb:
                self._synthetic_actions.append("HUB_PREV")
            if rb_pressed and not self._prev_rb:
                self._synthetic_actions.append("HUB_NEXT")

        self._prev_lb = lb_pressed
        self._prev_rb = rb_pressed
        self._prev_start = start_pressed

    def consume_synthetic_actions(self) -> list[str]:
        out = list(self._synthetic_actions)
        self._synthetic_actions.clear()
        return out

    def handle_device_event(self, event: pygame.event.Event) -> None:
        if sdl_controller is None:
            return
        if event.type == pygame.CONTROLLERDEVICEADDED:
            self._try_add_controller(event.device_index)
        elif event.type == pygame.CONTROLLERDEVICEREMOVED:
            self._controllers.pop(event.instance_id, None)

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

        if event.type == pygame.MOUSEMOTION:
            x, y = event.pos
            actions.append(f"MOUSE_HOVER:{x}:{y}")

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            x, y = event.pos
            actions.append(f"MOUSE_CLICK:{x}:{y}")

        if event.type == pygame.CONTROLLERBUTTONDOWN:
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

        if (
            event.type == pygame.CONTROLLERAXISMOTION
            and self._cooldown <= 0.0
            and abs(event.value) >= self.config.stick_deadzone
        ):
            if event.axis == pygame.CONTROLLER_AXIS_LEFTX:
                actions.append("MOVE_RIGHT" if event.value > 0 else "MOVE_LEFT")
                self._cooldown = self.config.repeat_cooldown_s
            elif event.axis == pygame.CONTROLLER_AXIS_LEFTY:
                actions.append("MOVE_DOWN" if event.value > 0 else "MOVE_UP")
                self._cooldown = self.config.repeat_cooldown_s

        return actions

    def _try_add_controller(self, device_index: int) -> None:
        if sdl_controller is None or not sdl_controller.is_controller(device_index):
            return
        controller = sdl_controller.Controller(device_index)
        self._controllers[controller.as_joystick().get_instance_id()] = controller

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
