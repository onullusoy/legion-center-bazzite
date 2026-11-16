import { call } from '@decky/api';
import { ButtonItem, Field, PanelSection, PanelSectionRow, SliderField, ToggleField } from '@decky/ui';
import { useEffect, useState } from 'react';

type Color = { red: number; green: number; blue: number };
type SleepLedStatus = { success: boolean; supported?: boolean; enabled?: boolean; error?: string };
type RgbStatus = { success: boolean; supported?: boolean; writable?: boolean; brightness?: number; color?: Color; error?: string };
type Diagnostics = {
  model: string; bios: string; kernel: string; os: string; os_version: string;
  services: Record<string, string>; fan_interface: boolean; fan_module_loaded: boolean;
  versions: Record<string, string>;
  controller_present: boolean; gyro_devices: number; rgb_supported: boolean;
};
type Snapshot = { sleep_led: SleepLedStatus; rgb: RgbStatus; diagnostics: Diagnostics };

function hueColor(hue: number): Color {
  const h = ((hue % 360) + 360) % 360 / 60;
  const x = 1 - Math.abs(h % 2 - 1);
  const triplets = [[1, x, 0], [x, 1, 0], [0, 1, x], [0, x, 1], [x, 0, 1], [1, 0, x]];
  const [red, green, blue] = triplets[Math.floor(h)];
  return { red: Math.round(red * 100), green: Math.round(green * 100), blue: Math.round(blue * 100) };
}

function colorHue(color: Color): number {
  const { red: r, green: g, blue: b } = color;
  const max = Math.max(r, g, b), delta = max - Math.min(r, g, b);
  if (!delta) return 0;
  const hue = max === r ? (g - b) / delta : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return Math.round((hue * 60 + 360) % 360);
}

export function SleepLighting({ initial }: { initial: SleepLedStatus }) {
  const [state, setState] = useState(initial);
  const [busy, setBusy] = useState(false);
  const update = async (enabled: boolean) => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await call<[boolean], SleepLedStatus>('set_sleep_led', enabled);
      setState(previous => result.success ? result : { ...previous, error: result.error || 'The sleep LED state could not be verified.' });
    } catch {
      setState(previous => ({ ...previous, error: 'The sleep LED request failed.' }));
    } finally { setBusy(false); }
  };
  return <PanelSection title="Sleep lighting">
    <PanelSectionRow><ToggleField label="Enable sleep LED"
      description="Controls the power-button indicator during sleep, independently of its awake state."
      checked={Boolean(state.enabled)} disabled={busy || !state.supported} onChange={value => { void update(value); }} /></PanelSectionRow>
    {state.error && <PanelSectionRow><Field label="Status">{state.error}</Field></PanelSectionRow>}
  </PanelSection>;
}

export function JoystickLighting({ initial }: { initial: RgbStatus }) {
  const [state, setState] = useState(initial);
  const [brightness, setBrightness] = useState(initial.brightness ?? 0);
  const [color, setColor] = useState<Color>(initial.color ?? { red: 100, green: 100, blue: 100 });
  const [hue, setHue] = useState(colorHue(color));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>();
  const apply = async (nextColor: Color = color) => {
    if (busy || !state.writable) return;
    setBusy(true); setMessage(undefined);
    try {
      const result = await call<[number, Color], RgbStatus>('set_joystick_rgb', brightness, nextColor);
      if (result.success && result.color && typeof result.brightness === 'number') {
        setState(result); setColor(result.color); setHue(colorHue(result.color)); setBrightness(result.brightness);
        setMessage('Applied and verified.');
      } else setMessage(result.error || 'The RGB state could not be verified.');
    } catch { setMessage('The RGB request failed.'); }
    finally { setBusy(false); }
  };
  if (!state.supported) return <PanelSection title="Joystick lighting"><PanelSectionRow><Field label="Status">{state.error || 'Native RGB control is unavailable.'}</Field></PanelSectionRow></PanelSection>;
  const disabled = busy || !state.writable;
  return <PanelSection title="Joystick lighting">
    <PanelSectionRow><SliderField label="Brightness" value={brightness} min={0} max={100} step={1}
      showValue editableValue={false} valueSuffix="%" disabled={disabled} onChange={value => setBrightness(Math.round(value))} /></PanelSectionRow>
    <PanelSectionRow><SliderField label="Color hue" value={hue} min={0} max={359} step={1}
      showValue editableValue={false} valueSuffix="°" disabled={disabled} onChange={value => { setHue(value); setColor(hueColor(value)); }} /></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => { void apply(); }}>Apply lighting</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={disabled} onClick={() => { void apply({ red: 100, green: 100, blue: 100 }); }}>Apply white</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Status">{message || state.error || 'Changes apply only when selected. Other RGB tools may update these lights.'}</Field></PanelSectionRow>
  </PanelSection>;
}

export function SystemDiagnostics({ initial }: { initial: Diagnostics }) {
  const [state, setState] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const refresh = async () => {
    setBusy(true); setError(undefined);
    try { setState(await call<[], Diagnostics>('get_system_diagnostics')); }
    catch { setError('Diagnostics could not be refreshed.'); }
    finally { setBusy(false); }
  };
  return <PanelSection title="System diagnostics">
    <PanelSectionRow><Field label="Device">{state.model}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="System">{state.os} {state.os_version}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="BIOS">{state.bios}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Kernel">{state.kernel}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Fan backend">{state.fan_module_loaded && state.fan_interface ? 'Available' : 'Unavailable'}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Controller">{state.controller_present ? 'Detected' : 'Not detected'}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Gyro devices">{state.gyro_devices} detected; data flow requires a motion test</Field></PanelSectionRow>
    {Object.entries(state.services).map(([name, status]) => <PanelSectionRow key={name}><Field label={name}>{status}</Field></PanelSectionRow>)}
    {Object.entries(state.versions).map(([name, version]) => <PanelSectionRow key={`version-${name}`}><Field label={`${name} version`}>{version}</Field></PanelSectionRow>)}
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => { void refresh(); }}>Refresh diagnostics</ButtonItem></PanelSectionRow>
    {error && <PanelSectionRow><Field label="Error">{error}</Field></PanelSectionRow>}
  </PanelSection>;
}

export default function CommunityFeatures({ view }: { view: 'sleep' | 'rgb' | 'lighting' | 'diagnostics' }) {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    call<[], Snapshot>('get_community_features').then(value => { if (active) setSnapshot(value); })
      .catch(() => { if (active) setError('Additional device features could not be loaded.'); });
    return () => { active = false; };
  }, []);
  if (!snapshot) return <PanelSection title="Device features"><PanelSectionRow><Field label="Status">{error || 'Loading…'}</Field></PanelSectionRow></PanelSection>;
  if (view === 'sleep') return <SleepLighting initial={snapshot.sleep_led} />;
  if (view === 'rgb') return <JoystickLighting initial={snapshot.rgb} />;
  if (view === 'lighting') return <>
    <SleepLighting initial={snapshot.sleep_led} />
    <JoystickLighting initial={snapshot.rgb} />
  </>;
  return <SystemDiagnostics initial={snapshot.diagnostics} />;
}
