import { call } from '@decky/api';

export type NightModeStatus = {
  success: boolean; active: boolean; pending: boolean; recoverable: boolean;
  available: boolean; verified: boolean; error?: string | null;
};
export type PowerAutomationConfig = { enabled: boolean; ac_slot: string; battery_slot: string };
export type SleepSummary = {
  started_at: number | null; ended_at: number | null; duration_seconds: number | null;
  battery_before: number | null; battery_after: number | null;
  battery_change_percentage: number | null; battery_loss_percentage: number | null;
  loss_per_hour: number | null; energy_change_wh: number | null; average_battery_drain_w: number | null;
};
export type ResumeHealth = {
  checked_at: number | null; controller_present: boolean | null;
  fan_curve: string; awake_led: string; sleep_led: string; inputplumber: string;
  repairs_performed: false;
};
export type AutomationStatus = {
  success: boolean; config: PowerAutomationConfig; source: 'ac' | 'battery' | 'unknown';
  custom_fan_enabled: boolean; active_slot: string | null;
  last_transition: { success: boolean; applied?: boolean; slot?: string; reason?: string; error?: string } | null;
  error?: string | null; sleep_monitor: string; sleep_measurement: string; sleep_error?: string | null;
  last_sleep: SleepSummary | null; sleep_history: SleepSummary[]; resume_health: ResumeHealth | null;
  night: NightModeStatus;
};

export const getAutomationStatus = () => call<[], AutomationStatus>('get_automation_status');
export const setPowerAutomation = (config: PowerAutomationConfig) => call<[PowerAutomationConfig], AutomationStatus>('set_power_automation', config);
export const applyPowerProfileNow = () => call<[], AutomationStatus>('apply_power_profile_now');
export const getNightModeStatus = () => call<[], NightModeStatus>('get_night_mode_status');
export const setNightMode = (enabled: boolean) => call<[boolean], NightModeStatus>('set_night_mode', enabled);
export const refreshResumeHealth = () => call<[], { success: boolean; health?: ResumeHealth; error?: string }>('refresh_resume_health');
