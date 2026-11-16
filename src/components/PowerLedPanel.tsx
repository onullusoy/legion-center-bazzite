import { Field, PanelSection, PanelSectionRow, ToggleField } from '@decky/ui';
import { useSelector } from 'react-redux';
import { usePowerLed } from '../hooks/ui';
import { RootState } from '../redux-modules/store';

export default function PowerLedPanel() {
  const { powerLedEnabled, setPowerLed } = usePowerLed();
  const { supportsPowerLed, powerLedBusy, powerLedError } = useSelector((state: RootState) => state.ui);
  return <PanelSection title="Lighting">
    <PanelSectionRow><ToggleField label="Enable Power Button LED"
      description="Power button indicator while awake. Joystick RGB and sleep lighting are separate."
      checked={powerLedEnabled} disabled={powerLedBusy || !supportsPowerLed} onChange={setPowerLed} /></PanelSectionRow>
    {powerLedError && <PanelSectionRow><Field label="Power LED error">{powerLedError}</Field></PanelSectionRow>}
  </PanelSection>;
}
