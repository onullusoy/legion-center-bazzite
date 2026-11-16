import { ButtonItem, ConfirmModal, Field, PanelSection, PanelSectionRow, showModal } from '@decky/ui';
import { useAcpiCallDkms } from '../hooks/ui';

export default function AcpiCallPanel() {
  const { acpiCallDkmsEnabled, acpiCallDkmsBusy, acpiCallDkmsError, setAcpiCallDkmsEnabled } = useAcpiCallDkms();
  const repair = () => showModal(<ConfirmModal
    strTitle="Repair fan support?"
    strDescription="Checks the module for your Bazzite kernel. Keep the device awake until complete."
    strOKButtonText="Repair"
    onOK={() => { setAcpiCallDkmsEnabled(true); }}
  />);
  return <PanelSection title="System">
    <PanelSectionRow><Field label="Fan support">{acpiCallDkmsBusy ? 'Working…' : acpiCallDkmsEnabled ? 'Ready' : 'Repair needed'}</Field></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={acpiCallDkmsBusy} onClick={repair}>Repair fan support</ButtonItem></PanelSectionRow>
    {acpiCallDkmsError && <PanelSectionRow><Field label="Error">{acpiCallDkmsError}</Field></PanelSectionRow>}
  </PanelSection>;
}
