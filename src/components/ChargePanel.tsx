import { Field, PanelSection, PanelSectionRow, ToggleField } from '@decky/ui';
import { useChargeLimitEnabled } from '../hooks/ui';

export default function ChargePanel() {
  const state = useChargeLimitEnabled();
  return <PanelSection title="Battery protection">
    <PanelSectionRow><ToggleField label="Charge limit (80%)" checked={state.chargeLimitEnabled}
      disabled={!state.supportsChargeLimit || state.chargeLimitBusy}
      description="Changes are checked against the battery interface."
      onChange={state.setChargeLimit} /></PanelSectionRow>
    {state.chargeLimitError && <PanelSectionRow><Field label="Error">{state.chargeLimitError}</Field></PanelSectionRow>}
  </PanelSection>;
}
