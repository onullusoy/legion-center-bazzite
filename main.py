import os
import asyncio
import copy
import json
import platform
import logging

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`

import decky
import battery_charge
import fan_capability
import fan_control
import fan_presets
import device_features
import community_features
import device_automation
import lighting_transactions
import controller_support
import legion_configurator
import legion_space
import controller_enums
import controllers
import file_timeout
import plugin_update
import controller_settings as settings

try:
    from acpi_enabler import AcpiEnabler
except Exception as e:
    AcpiEnabler = None
    logging.error(f"failed to import AcpiEnabler|{e}")

try:
    LOG_LOCATION = f"/tmp/legionCenter.log"
    logging.basicConfig(
        level = logging.INFO,
        filename = LOG_LOCATION,
        format="[%(asctime)s | %(filename)s:%(lineno)s:%(funcName)s] %(levelname)s: %(message)s",
        filemode = 'w',
        force = True)
except Exception as e:
    logging.error(f"exception|{e}")

class Plugin:
    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        decky.logger.info("Legion Decky starting up")
        self._acpi_call_busy = False

        await self._auto_install_fan_support()

        settings.remove_transient_status()
        saved = settings.get_settings()
        night_state = saved.get('nightMode') or {}
        night_requested = isinstance(night_state, dict) and (night_state.get('active') or night_state.get('pending'))
        if saved.get("chargeLimitEnabled", False):
            result = self._set_charge_limit_hardware(True)
            if not result.success:
                decky.logger.error(
                    f"failed to restore saved charge limit: {result.error}"
                )

        if saved.get("customFanCurvesEnabled", False) and self._fan_backend_available():
            profile = (saved.get("fan") or {}).get("default")
            if profile:
                try:
                    if not fan_control.apply_fan_profile(
                        profile,
                        legion_space.set_full_fan_speed,
                        legion_space.set_active_fan_curve,
                    ):
                        decky.logger.error("failed to restore the saved default fan profile")
                except ValueError as error:
                    decky.logger.error(f"saved default fan profile is invalid: {error}")

        if not night_requested and 'powerLedEnabled' in saved:
            led_result = device_features.set_led(bool(saved['powerLedEnabled']), legion_space._acpi_call, legion_space._acpi_read)
            if not led_result['success']:
                decky.logger.error(f"Saved power LED preference failed: {led_result.get('error')}")

        if not night_requested and type(saved.get('sleepLedEnabled')) is bool:
            sleep_result = community_features.set_sleep_led(
                saved['sleepLedEnabled'], legion_space._acpi_call, legion_space._acpi_read)
            if not sleep_result['success']:
                decky.logger.error('Saved sleep LED preference could not be verified')

        runtime = self._ensure_device_automation()
        night_result = runtime.night.startup()
        if night_requested and not night_result['success']:
            decky.logger.error('Saved night mode could not be verified; check its recovery status')
        self._device_automation_task = asyncio.create_task(runtime.run())

    async def _auto_install_fan_support(self):
        """Build and load acpi_call once per kernel when it is missing."""
        if AcpiEnabler is None:
            return
        try:
            if fan_capability.ensure_acpi_call_available():
                return
            kernel = platform.release()
            marker = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, 'fan-support-attempt.json')
            try:
                with open(marker) as handle:
                    if json.load(handle).get('kernel') == kernel:
                        return  # already tried for this kernel; use Repair to retry
            except (OSError, ValueError):
                pass
            decky.logger.info(f'fan support missing; installing for kernel {kernel}')
            self._acpi_call_busy = True
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, AcpiEnabler(verbose=True).enable)
                decky.logger.info('fan support installed')
            except Exception as error:
                decky.logger.error(f'automatic fan support install failed: {error}')
                os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
                with open(marker, 'w') as handle:
                    json.dump({'kernel': kernel, 'error': str(error)}, handle)
            finally:
                self._acpi_call_busy = False
        except Exception as error:
            decky.logger.error(f'fan support check failed: {error}')

    def _ensure_device_automation(self):
        runtime = getattr(self, '_device_automation', None)
        if runtime is None:
            night = lighting_transactions.NightMode(
                settings.get_settings, settings.merge_settings,
                lambda: device_features.led_status(legion_space._acpi_call, legion_space._acpi_read),
                lambda enabled: device_features.set_led(enabled, legion_space._acpi_call, legion_space._acpi_read),
                lambda: community_features.sleep_led_status(legion_space._acpi_call, legion_space._acpi_read),
                lambda enabled: community_features.set_sleep_led(enabled, legion_space._acpi_call, legion_space._acpi_read),
            )
            runtime = device_automation.DeviceAutomation(
                settings.get_settings, settings.merge_settings,
                lambda profile: fan_control.apply_fan_profile(
                    profile, legion_space.set_full_fan_speed, legion_space.set_active_fan_curve),
                self._collect_resume_health, night,
            )
            self._device_automation = runtime
        return runtime

    async def _collect_resume_health(self):
        loop = asyncio.get_running_loop()
        diagnostics = await loop.run_in_executor(None, community_features.diagnostics)
        # Keep each ACPI query/read pair on the event-loop thread: acpi_call has a shared result buffer.
        return device_automation.collect_resume_health(
            settings.get_settings(), diagnostics, legion_space._acpi_call, legion_space._acpi_read,
            lambda: device_features.led_status(legion_space._acpi_call, legion_space._acpi_read),
            lambda: community_features.sleep_led_status(legion_space._acpi_call, legion_space._acpi_read),
        )

    async def get_automation_status(self):
        return self._ensure_device_automation().status()

    async def set_power_automation(self, config):
        return self._ensure_device_automation().configure(config)

    async def apply_power_profile_now(self):
        return self._ensure_device_automation().apply_now()

    async def get_night_mode_status(self):
        return self._ensure_device_automation().night.status()

    async def set_night_mode(self, enabled):
        return self._ensure_device_automation().night.set_enabled(enabled)

    async def refresh_resume_health(self):
        try:
            health = await self._collect_resume_health()
            settings.merge_settings({'resumeHealth': health})
            return {'success': True, 'health': health}
        except Exception:
            return {'success': False, 'error': 'Resume health could not be read or saved. No automatic repair was attempted.'}

    async def get_controller_status(self):
        snapshot = settings.get_settings().get('directTouchpadRoute')
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, controller_support.InputRouter().status, snapshot)

    async def set_direct_touchpad(self, enabled):
        if type(enabled) is not bool:
            return {'success': False, 'message': 'The pointer route value must be boolean.'}
        if getattr(self, '_pointer_busy', False):
            return {'success': False, 'message': 'A pointer routing request is already running.'}
        self._pointer_busy = True
        try:
            snapshot = settings.get_settings().get('directTouchpadRoute')
            router = controller_support.InputRouter()
            operation = router.repair if enabled else router.restore
            result, saved = await asyncio.get_running_loop().run_in_executor(None, operation, snapshot)
            if result['success']:
                settings.set_setting('directTouchpadRoute', saved)
            return result
        finally:
            self._pointer_busy = False

    async def test_gyro_motion(self):
        if getattr(self, '_gyro_test_busy', False):
            return {'success': False, 'message': 'A gyro test is already running.'}
        self._gyro_test_busy = True
        try:
            return await asyncio.get_running_loop().run_in_executor(None, controller_support.sample_tablet_gyro)
        finally:
            self._gyro_test_busy = False

    async def get_community_features(self):
        sleep_led = community_features.sleep_led_status(
            legion_space._acpi_call, legion_space._acpi_read)
        loop = asyncio.get_running_loop()
        diagnostics = await loop.run_in_executor(None, community_features.diagnostics)
        return {
            'sleep_led': sleep_led,
            'rgb': community_features.rgb_status(),
            'diagnostics': diagnostics,
        }

    async def set_sleep_led(self, enabled):
        if self._night_mode_blocks_lighting():
            return {'success': False, 'error': 'Restore lighting from night mode before editing individual lights.'}
        result = community_features.set_sleep_led(
            enabled, legion_space._acpi_call, legion_space._acpi_read)
        if result['success']:
            settings.set_setting('sleepLedEnabled', result['enabled'])
        return result

    async def set_joystick_rgb(self, brightness, color):
        if self._night_mode_blocks_lighting():
            return {'success': False, 'error': 'Restore lighting from night mode before editing individual lights.'}
        # Explicit writes only: do not continuously override Steam or another RGB tool.
        return community_features.set_rgb(brightness, color)

    def _night_mode_blocks_lighting(self):
        state = settings.get_settings().get('nightMode')
        return isinstance(state, dict) and (state.get('active') is True or state.get('pending') is True)

    async def get_system_diagnostics(self):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, community_features.diagnostics)

    async def get_settings(self):
        # Capability and live hardware fields are response-only. Mutating the
        # SettingsManager-owned dictionary here causes those transient values
        # to be persisted the next time any real user setting is saved.
        results = copy.deepcopy(settings.get_settings())

        try:
            results['pluginVersionNum'] = f'{decky.DECKY_PLUGIN_VERSION}'

            results['supportsCustomFanCurves'] = self._fan_backend_available()
        except Exception as e:
            decky.logger.error(e)

        led_status = device_features.led_status(legion_space._acpi_call, legion_space._acpi_read)
        results['supportsPowerLed'] = led_status['supported']
        results['powerLedError'] = led_status['error']
        if led_status['supported']:
            results['powerLedEnabled'] = led_status['enabled']
        controller_status = device_features.controller_status()
        results['supportsControllerRemapping'] = controller_status['supported']
        results['controllerRemappingError'] = controller_status['error']

        quick_profiles, active_slot = fan_presets.initial_state(results)
        results['bazziteFanProfiles'] = quick_profiles
        results['bazziteActiveFanProfile'] = active_slot

        charge_status = self._get_charge_limit_status()
        results['supportsChargeLimit'] = charge_status.supported
        results['chargeLimitEnabled'] = bool(charge_status.enabled)
        results['chargeLimitBackend'] = charge_status.backend
        results['chargeLimitError'] = charge_status.error

        try:
            results['acpiCallDkmsEnabled'] = self._acpi_call_dkms_enabled()
            results['acpiCallDkmsBusy'] = getattr(self, '_acpi_call_busy', False)
            results['acpiCallDkmsInstalled'] = fan_capability.fan_support_installed()
        except Exception as e:
            decky.logger.error(f'error while checking acpi_call dkms status {e}')

        return results

    def _acpi_call_dkms_enabled(self):
        try:
            return self._fan_backend_available()
        except Exception as e:
            decky.logger.error(f'error while checking acpi_call dkms status {e}')
            return False

    def _fan_backend_available(self):
        return fan_capability.ensure_acpi_call_available()

    def _legacy_charge_getter(self):
        return legion_space.get_charge_limit if self._fan_backend_available() else None

    def _get_charge_limit_status(self):
        return battery_charge.get_charge_limit_status(
            legacy_get=self._legacy_charge_getter()
        )

    def _set_charge_limit_hardware(self, enabled: bool):
        legacy_get = self._legacy_charge_getter()
        legacy_set = legion_space.set_charge_limit if legacy_get else None
        return battery_charge.set_charge_limit(
            enabled,
            legacy_get=legacy_get,
            legacy_set=legacy_set,
        )

    async def get_acpi_call_dkms_status(self):
        return {
            'enabled': self._acpi_call_dkms_enabled(),
            'installed': fan_capability.fan_support_installed(),
            'managed': bool(
                AcpiEnabler is not None and AcpiEnabler.ACPI_CALL_CONF_PATH.exists()
            ),
            'busy': getattr(self, '_acpi_call_busy', False)
        }

    async def set_acpi_call_dkms_enabled(self, enabled: bool):
        if AcpiEnabler is None:
            decky.logger.error('set_acpi_call_dkms_enabled called but AcpiEnabler failed to import')
            return {'success': False, 'error': 'AcpiEnabler is unavailable on this system'}

        if getattr(self, '_acpi_call_busy', False):
            return {'success': False, 'error': 'An acpi_call dkms operation is already in progress'}

        self._acpi_call_busy = True
        try:
            workdir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, 'acpi-enabler-work')
            enabler = AcpiEnabler(workdir=workdir, verbose=True)

            loop = asyncio.get_running_loop()
            if enabled:
                await loop.run_in_executor(None, enabler.enable)
            else:
                await loop.run_in_executor(None, enabler.disable)

            status = await self.get_acpi_call_dkms_status()
            status['busy'] = False
            if enabled and not status['enabled']:
                return {
                    'success': False,
                    'enabled': False,
                    'error': 'acpi_call installation completed but /proc/acpi/call is unavailable'
                }
            return {'success': True, **status}
        except Exception as e:
            decky.logger.error(f'error while {"enabling" if enabled else "disabling"} acpi_call dkms|{e}')
            return {'success': False, 'error': str(e)}
        finally:
            self._acpi_call_busy = False

    async def save_controller_settings(self, controller, currentGameId):
        controllerProfiles = controller.get('controllerProfiles')
        controllerPerGameProfilesEnabled = controller.get('perGameProfilesEnabled') or False
        controllerRemappingEnabled  = controller.get('controllerRemappingEnabled') or False

        if controllerRemappingEnabled:
            compatibility = device_features.controller_status()
            if not compatibility['supported']:
                return {'success':False,'error':compatibility['error']}

        settings.set_setting('controllerPerGameProfilesEnabled', controllerPerGameProfilesEnabled)
        settings.set_setting('controllerRemappingEnabled', controllerRemappingEnabled)
        result = settings.set_all_controller_profiles(controllerProfiles)

        if controllerRemappingEnabled:
            # double-sync just in case the first one doesn't register
            for _ in range(2):
                # sync settings.json to actual controller hardware
                if currentGameId:
                    controllers.sync_controller_profile_settings(currentGameId)
                    # sync touchpad
                    controllers.sync_touchpad(currentGameId)
                    # sync gyros
                    controllers.sync_gyros(currentGameId)
        return result

    async def disable_fan_profiles(self, resetCurve = False):
        settings.set_setting('customFanCurvesEnabled', False)
        return fan_control.restore_firmware_fan_control(
            legion_space.set_full_fan_speed,
            legion_space.set_tdp_mode,
            resetCurve,
        )

    async def save_fan_settings(self, fanInfo, currentGameId):
        try:
            fan_profiles = fanInfo.get('fanProfiles', {})
            per_game = bool(fanInfo.get('fanPerGameProfilesEnabled', False))
            enabled = bool(fanInfo.get('customFanCurvesEnabled', False))
            for profile in fan_profiles.values():
                fan_control.parse_fan_profile(profile)
            quick = fanInfo.get('quickProfiles')
            active_slot = fanInfo.get('activeQuickProfile', '1')
            if quick is not None:
                quick, active_slot = fan_presets.validate_slots(quick, active_slot)
                if not per_game and fan_profiles.get('default') != quick[active_slot]:
                    raise ValueError('Selected quick profile does not match the active fan curve')
            profile = fan_profiles.get(currentGameId) if per_game else None
            profile = profile or fan_profiles.get('default')
            if enabled:
                if not profile or not self._fan_backend_available():
                    raise ValueError('Fan backend or active curve is unavailable')
                success = fan_control.apply_fan_profile(profile,
                    legion_space.set_full_fan_speed, legion_space.set_active_fan_curve)
            elif self._fan_backend_available():
                success = fan_control.restore_firmware_fan_control(
                    legion_space.set_full_fan_speed, legion_space.set_tdp_mode, True)
            else:
                success = True
            if not success:
                return False
            updated = {'fanPerGameProfilesEnabled':per_game,
                       'customFanCurvesEnabled':enabled, 'fan':fan_profiles}
            if quick is not None:
                updated.update(bazziteFanProfiles=quick, bazziteActiveFanProfile=active_slot)
            settings.merge_settings(updated)
            return True
        except Exception as error:
            decky.logger.error(f'Fan profile save failed: {error}')
            return False


    async def set_power_led(self, enabled):
        if self._night_mode_blocks_lighting():
            return {'success': False, 'error': 'Restore lighting from night mode before editing individual lights.'}
        result = device_features.set_led(enabled, legion_space._acpi_call, legion_space._acpi_read)
        if result['success']:
            settings.set_setting('powerLedEnabled', result['enabled'])
        else:
            decky.logger.error(f"Power LED update failed: {result.get('error')}")
        return result

    async def set_charge_limit(self, enabled):
        try:
            result = self._set_charge_limit_hardware(bool(enabled))
            if result.success:
                settings.set_setting('chargeLimitEnabled', bool(result.enabled))
            else:
                decky.logger.error(f'error while setting charge limit: {result.error}')
            return result.to_dict()
        except Exception as e:
            decky.logger.error(f'error while setting charge limit {e}')
            return {'success': False, 'error': str(e)}

    async def remap_button(self, button: str, action: str):
        compatibility = device_features.controller_status()
        if not compatibility['supported']:
            return {'success':False,'error':compatibility['error']}
        decky.logger.info(f"remap_button {button} {action}")
        controller_code = None
        if button in ['Y3', 'M2', 'M3']:
            controller_code = controller_enums.Controller['RIGHT'].value
        elif button in ['Y1', 'Y2']:
            controller_code = controller_enums.Controller['LEFT'].value
        if not controller_code:
            return
        btn_code = controller_enums.RemappableButtons[button].value
        action_code = controller_enums.RemapActions[action].value
        remap_command = legion_configurator.create_button_remap_command(controller_code, btn_code, action_code)

        legion_configurator.send_command(remap_command)

    async def set_touchpad(self, enable: bool):
        t_toggle = legion_configurator.create_touchpad_command(enable)
        decky.logger.info(t_toggle)

        legion_configurator.send_command(t_toggle)

    async def ota_update(self):
        # trigger ota update
        try:
            with file_timeout.time_limit(15):
                plugin_update.ota_update()
        except Exception as e:
            logging.error(e)

    # Function called first during the unload process, utilize this to handle your plugin being removed
    async def _unload(self):
        decky.logger.info("Legion Decky shutting down")
        task = getattr(self, '_device_automation_task', None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        decky.logger.info("Migrating")
        # Here's a migration example for logs:
        # - `~/.config/decky-template/template.log` will be migrated to `decky.DECKY_PLUGIN_LOG_DIR/template.log`
        decky.migrate_logs(os.path.join(decky.DECKY_USER_HOME,
                                               ".config", "decky-template", "template.log"))
        # Here's a migration example for settings:
        # - `~/homebrew/settings/template.json` is migrated to `decky.DECKY_PLUGIN_SETTINGS_DIR/template.json`
        # - `~/.config/decky-template/` all files and directories under this root are migrated to `decky.DECKY_PLUGIN_SETTINGS_DIR/`
        decky.migrate_settings(
            os.path.join(decky.DECKY_HOME, "settings", "template.json"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "decky-template"))
        # Here's a migration example for runtime data:
        # - `~/homebrew/template/` all files and directories under this root are migrated to `decky.DECKY_PLUGIN_RUNTIME_DIR/`
        # - `~/.local/share/decky-template/` all files and directories under this root are migrated to `decky.DECKY_PLUGIN_RUNTIME_DIR/`
        decky.migrate_runtime(
            os.path.join(decky.DECKY_HOME, "template"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "decky-template"))

    async def log_info(self, info):
        logging.info(info)
