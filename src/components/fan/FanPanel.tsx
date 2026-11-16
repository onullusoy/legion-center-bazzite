import { ButtonItem, Field, PanelSection, PanelSectionRow, ToggleField } from '@decky/ui';
import { useDispatch, useSelector } from 'react-redux';
import { useAcpiCallDkms } from '../../hooks/ui';
import { fanSlice } from '../../redux-modules/fanSlice';
import { RootState } from '../../redux-modules/store';
import FanCurveSliders from './FanCurveSliders';

const PROFILES = [
  { id: '1', name: 'Balanced' },
  { id: '2', name: 'Cooler' },
  { id: '3', name: 'Strong cooling' }
];

export default function FanPanel() {
  const { acpiCallDkmsEnabled } = useAcpiCallDkms();
  const dispatch = useDispatch();
  const fan = useSelector((state: RootState) => state.fan);
  const fullSpeed = Boolean(fan.fanProfiles.default?.fullFanSpeedEnabled);
  const active = fan.activeQuickProfile;
  return <PanelSection title="Fan control">
    <PanelSectionRow><ToggleField label="Full fan speed" checked={fullSpeed}
      onChange={value => dispatch(fanSlice.actions.setEnableFullFanSpeedMode(value))} /></PanelSectionRow>
    <PanelSectionRow><Field label="Quick profiles" /></PanelSectionRow>
      {PROFILES.map(profile => <PanelSectionRow key={profile.id}>
        <ButtonItem layout="below"
          onClick={() => dispatch(fanSlice.actions.selectQuickProfile(profile.id))}>
          {active === profile.id ? '● ' : ''}{profile.name}
        </ButtonItem>
      </PanelSectionRow>)}
    <PanelSectionRow><ToggleField label="Custom fan control" checked={fan.customFanCurvesEnabled}
      disabled={!acpiCallDkmsEnabled} onChange={value => dispatch(fanSlice.actions.setCustomFanCurvesEnabled(value))} /></PanelSectionRow>
    {fan.customFanCurvesEnabled && !fullSpeed && <FanCurveSliders />}
    <PanelSectionRow><Field label="Status">{fan.saveError ? 'Could not save' : fan.saveBusy ? 'Saving…' : 'Ready'}</Field></PanelSectionRow>
    {fan.saveError && <PanelSectionRow><Field label="Error">{fan.saveError}</Field></PanelSectionRow>}
    <PanelSectionRow><ButtonItem layout="below"
      onClick={() => dispatch(fanSlice.actions.resetRecommended())}>Reset to defaults</ButtonItem></PanelSectionRow>
  </PanelSection>;
}
