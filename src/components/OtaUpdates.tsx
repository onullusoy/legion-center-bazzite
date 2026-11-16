import { Field, PanelSection, PanelSectionRow } from '@decky/ui';
import { useSelector } from 'react-redux';
import { getPluginVersionNumSelector } from '../redux-modules/uiSlice';

export default function VersionPanel() {
  const version = useSelector(getPluginVersionNumSelector);
  return <PanelSection title="About">
    <PanelSectionRow><Field label="Version">{version}</Field></PanelSectionRow>
  </PanelSection>;
}
