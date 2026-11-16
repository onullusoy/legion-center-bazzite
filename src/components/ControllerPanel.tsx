import { call } from '@decky/api';
import { ButtonItem, Field, PanelSection, PanelSectionRow } from '@decky/ui';
import { useEffect, useState } from 'react';

type ControllerStatus = {
  success: boolean; controller_present?: boolean; touchpad_detected?: boolean;
  direct_pointer?: boolean; can_restore?: boolean; message: string;
  gyro?: Record<string, { available: boolean; filtered_sources: number }>;
};
type GyroResult = { success: boolean; samples?: number; motion_detected?: boolean; message: string };

function useControllerStatus() {
  const [state, setState] = useState<ControllerStatus>();
  useEffect(() => {
    let active = true;
    call<[], ControllerStatus>('get_controller_status').then(result => { if (active) setState(result); })
      .catch(() => { if (active) setState({ success: false, message: 'Controller information could not be loaded.' }); });
    return () => { active = false; };
  }, []);
  return { state, setState };
}

export function TouchpadPanel() {
  const { state, setState } = useControllerStatus();
  const [busy, setBusy] = useState(false);
  const update = async (enabled: boolean) => {
    if (busy) return;
    setBusy(true);
    try { setState(await call<[boolean], ControllerStatus>('set_direct_touchpad', enabled)); }
    catch { setState(previous => ({ ...previous, success: false, message: 'The pointer routing request failed.' })); }
    finally { setBusy(false); }
  };
  return <PanelSection title="Touchpad pointer">
    <PanelSectionRow><Field label="Physical touchpad">{state ? state.touchpad_detected ? 'Detected' : 'Not detected' : 'Checking…'}</Field></PanelSectionRow>
    <PanelSectionRow><Field label="Direct pointer">{state?.direct_pointer ? 'Enabled' : 'Not enabled'}</Field></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || !state?.controller_present}
      description="Adds a direct pointer in Gaming or Desktop Mode without replacing your gamepad or profile."
      onClick={() => { void update(true); }}>Repair touchpad pointer</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || !state?.can_restore}
      onClick={() => { void update(false); }}>Undo pointer repair</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Status">{busy ? 'Updating pointer route…' : state?.message || 'Loading…'}</Field></PanelSectionRow>
  </PanelSection>;
}

export function GyroPanel() {
  const { state } = useControllerStatus();
  const [result, setResult] = useState<GyroResult>();
  const [busy, setBusy] = useState(false);
  const test = async () => {
    if (busy) return;
    setBusy(true);
    try { setResult(await call<[], GyroResult>('test_gyro_motion')); }
    catch { setResult({ success: false, message: 'The motion test could not be completed.' }); }
    finally { setBusy(false); }
  };
  return <PanelSection title="Gyro test">
    {['Center', 'Left', 'Right'].map(name => <PanelSectionRow key={name}><Field label={name === 'Center' ? 'Tablet source' : `${name} controller`}>
      {!state ? 'Checking…' : state.gyro?.[name]?.available ? 'Capability detected' : 'Not advertised'}
    </Field></PanelSectionRow>)}
    <PanelSectionRow><ButtonItem layout="below" disabled={busy}
      description="Move the device for three seconds. This reads exposed tablet gyro values without changing input routing."
      onClick={() => { void test(); }}>{busy ? 'Move the device…' : 'Test tablet motion'}</ButtonItem></PanelSectionRow>
    <PanelSectionRow><Field label="Test result">{result?.message || 'Controller gyro capabilities are listed separately; they are not proof of data flow.'}</Field></PanelSectionRow>
  </PanelSection>;
}
