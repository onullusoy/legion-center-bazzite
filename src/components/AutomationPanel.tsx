import { ButtonItem, Field, PanelSection, PanelSectionRow, ToggleField } from '@decky/ui';
import { useEffect, useState } from 'react';
import {
  applyPowerProfileNow, AutomationStatus, getAutomationStatus, getNightModeStatus,
  NightModeStatus, PowerAutomationConfig, refreshResumeHealth, ResumeHealth,
  setNightMode, setPowerAutomation, SleepSummary
} from '../backend/automation';

function useAutomationStatus() {
  const [state, setState] = useState<AutomationStatus>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let mounted = true;
    getAutomationStatus().then(value => { if (mounted) setState(value); })
      .catch(() => { if (mounted) setError('Automation status could not be loaded.'); });
    return () => { mounted = false; };
  }, []);
  return { state, setState, error, setError };
}

export function NightModePanel() {
  const [state, setState] = useState<NightModeStatus>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let mounted = true;
    getNightModeStatus().then(value => { if (mounted) setState(value); })
      .catch(() => { if (mounted) setError('Night mode status could not be loaded.'); });
    return () => { mounted = false; };
  }, []);
  const update = async (enabled: boolean) => {
    if (busy) return;
    setBusy(true); setError(undefined);
    try {
      const result = await setNightMode(enabled);
      setState(result);
      if (!result.success) setError(result.error || 'The lighting transaction could not be verified.');
    } catch { setError('The lighting request failed. The recovery snapshot is retained if the operation had started.'); }
    finally { setBusy(false); }
  };
  return <PanelSection title="Night mode">
    <PanelSectionRow><ToggleField label="Night mode" checked={Boolean(state?.active)}
      description="Turns off awake, sleep, and joystick lights. Turning it off restores the previous lighting state."
      disabled={busy || !state || (!state.available && !state.active)} onChange={value => { void update(value); }} /></PanelSectionRow>
    <PanelSectionRow><Field label="Status">{!state ? 'Loading…' : state.pending ? 'Recovery required' : state.verified ? 'All lights off and verified' : state.active ? 'Enabled; lighting changed externally' : state.available ? 'Off' : 'All three lighting interfaces are required'}</Field></PanelSectionRow>
    {state?.recoverable && <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => { void update(false); }}>Restore lighting</ButtonItem></PanelSectionRow>}
    {(error || state?.error) && <PanelSectionRow><Field label="Error">{error || state?.error}</Field></PanelSectionRow>}
  </PanelSection>;
}

const slotName = (slot: string | null) => slot === '1' ? '1 · Balanced' : slot === '2' ? '2 · Cooler' : slot === '3' ? '3 · Strong cooling' : 'Unavailable';
const nextSlot = (slot: string) => String(Number(slot) % 3 + 1);

export function FanAutomationPanel() {
  const { state, setState, error, setError } = useAutomationStatus();
  const [busy, setBusy] = useState(false);
  const configure = async (config: PowerAutomationConfig) => {
    if (busy) return;
    setBusy(true); setError(undefined);
    try {
      const result = await setPowerAutomation(config);
      if (result.success) setState(result);
      else setError(result.error || 'The automation configuration could not be saved.');
    } catch { setError('The automation request failed.'); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    if (busy) return;
    setBusy(true); setError(undefined);
    try {
      const result = await applyPowerProfileNow();
      if (result.config) setState(result);
      if (!result.success) setError(result.error || 'The matching profile could not be verified.');
    } catch { setError('The matching profile request failed.'); }
    finally { setBusy(false); }
  };
  if (!state) return <PanelSection title="Fan profile automation"><PanelSectionRow><Field label="Status">{error || 'Loading…'}</Field></PanelSectionRow></PanelSection>;
  return <PanelSection title="Fan profile automation">
    <PanelSectionRow><ToggleField label="Select profiles on power changes" checked={state.config.enabled} disabled={busy}
      description="Runs once when the charger is connected or removed. It does not repeatedly override manual profile choices."
      onChange={enabled => { void configure({ ...state.config, enabled }); }} /></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} description="Press to cycle the three existing profile slots."
      onClick={() => { void configure({ ...state.config, ac_slot: nextSlot(state.config.ac_slot) }); }}>On charger: {slotName(state.config.ac_slot)}</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} description="Press to cycle the three existing profile slots."
      onClick={() => { void configure({ ...state.config, battery_slot: nextSlot(state.config.battery_slot) }); }}>On battery: {slotName(state.config.battery_slot)}</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Power source">{state.source === 'ac' ? 'Charger' : state.source === 'battery' ? 'Battery' : 'Unavailable'}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Active profile">{slotName(state.active_slot)}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Custom fan control">{state.custom_fan_enabled ? 'On' : 'Off — automation will not turn it on'}</Field></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || !state.config.enabled || !state.custom_fan_enabled || state.source === 'unknown'}
      onClick={() => { void apply(); }}>Apply matching profile now</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Last result">{state.last_transition?.reason || (state.last_transition?.applied ? `Applied profile ${state.last_transition.slot}` : 'Waiting for a power transition')}</Field></PanelSectionRow>
    {(error || state.error) && <PanelSectionRow><Field label="Error">{error || state.error}</Field></PanelSectionRow>}
  </PanelSection>;
}

function duration(seconds: number | null) {
  if (seconds === null) return 'Unavailable';
  const minutes = Math.floor(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : minutes ? `${minutes}m` : `${Math.round(seconds)}s`;
}
function batteryChange(summary: SleepSummary) {
  if (summary.battery_change_percentage === null) return 'Unavailable';
  return `${summary.battery_change_percentage > 0 ? '+' : ''}${summary.battery_change_percentage}%`;
}

export function SleepHistoryPanel() {
  const { state, setState, error, setError } = useAutomationStatus();
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true); setError(undefined);
    try { setState(await getAutomationStatus()); }
    catch { setError('Sleep history could not be refreshed.'); }
    finally { setBusy(false); }
  };
  const last = state?.last_sleep;
  return <PanelSection title="Sleep battery summary">
    <PanelSectionRow><Field label="Sleep signal monitor">{state?.sleep_monitor || 'Loading…'}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Measurement readiness">{state?.sleep_measurement || 'Loading…'}</Field></PanelSectionRow>
    {!last && <PanelSectionRow><Field label="Status">No completed sleep cycle has been observed yet.</Field></PanelSectionRow>}
    {last && <>
      <PanelSectionRow><Field label="Last sleep duration">{duration(last.duration_seconds)}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Battery">{last.battery_before === null || last.battery_after === null ? 'Unavailable' : `${last.battery_before}% → ${last.battery_after}%`}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Battery change">{batteryChange(last)}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Loss per hour">{last.loss_per_hour === null ? 'Unavailable' : `${last.loss_per_hour}%/h`}</Field></PanelSectionRow>
      {last.average_battery_drain_w !== null && <PanelSectionRow><Field label="Average battery drain">{last.average_battery_drain_w} W</Field></PanelSectionRow>}
    </>}
    {state?.sleep_history.slice(-3).reverse().map((summary, index) => <PanelSectionRow key={`${summary.ended_at}-${index}`}><Field label={`Recent sleep ${index + 1}`}>{duration(summary.duration_seconds)} · {batteryChange(summary)}</Field></PanelSectionRow>)}
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => { void refresh(); }}>Refresh sleep summary</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Measurement">Uses real system sleep/resume signals. Battery percentages are coarse estimates.</Field></PanelSectionRow>
    {(error || state?.sleep_error) && <PanelSectionRow><Field label="Status">{error || state?.sleep_error}</Field></PanelSectionRow>}
  </PanelSection>;
}

const healthLabels: Record<string, string> = {
  verified: 'Verified', different: 'Changed', unavailable: 'Unavailable', automatic: 'Automatic control',
  not_configured: 'No preference saved', recovery_required: 'Night mode recovery required', full_speed: 'Full-speed mode verified'
};
const healthLabel = (value: string) => healthLabels[value] || value;

export function ResumeHealthPanel() {
  const { state, error, setError } = useAutomationStatus();
  const [health, setHealth] = useState<ResumeHealth | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (state) setHealth(state.resume_health); }, [state]);
  const refresh = async () => {
    setBusy(true); setError(undefined);
    try {
      const result = await refreshResumeHealth();
      if (result.success && result.health) setHealth(result.health);
      else setError(result.error || 'Resume health could not be checked.');
    } catch { setError('Resume health could not be checked.'); }
    finally { setBusy(false); }
  };
  return <PanelSection title="Resume health">
    {!health && <PanelSectionRow><Field label="Status">No resume check recorded. Select Check now for a read-only check.</Field></PanelSectionRow>}
    {health && <>
      <PanelSectionRow><Field label="Last check">{health.checked_at ? new Date(health.checked_at * 1000).toLocaleString() : 'Unavailable'}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Controller">{health.controller_present === null ? 'Unavailable' : health.controller_present ? 'Detected' : 'Not detected'}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="InputPlumber">{health.inputplumber}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Fan control">{healthLabel(health.fan_curve)}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Awake LED">{healthLabel(health.awake_led)}</Field></PanelSectionRow>
      <PanelSectionRow><Field label="Sleep LED">{healthLabel(health.sleep_led)}</Field></PanelSectionRow>
    </>}
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => { void refresh(); }}>Check now</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Actions performed">Read-only diagnostics. No controller restart or automatic repair.</Field></PanelSectionRow>
    {error && <PanelSectionRow><Field label="Error">{error}</Field></PanelSectionRow>}
  </PanelSection>;
}
