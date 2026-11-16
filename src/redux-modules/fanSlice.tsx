import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { Middleware } from 'redux';
import { call } from '@decky/api';
import { cloneDeep, merge } from 'lodash';
import { setCurrentGameId, setInitialState } from './extraActions';
import { RootState } from './store';

export type FanProfile = Record<string, number | boolean> & { fullFanSpeedEnabled: boolean };
type Profiles = Record<string, FanProfile>;
export const FAN_MINIMUMS: Record<number, number> = { 10:20, 20:20, 30:20, 40:25, 50:35, 60:50, 70:87, 80:87, 90:100, 100:100 };
const RECOMMENDED = [44,48,55,60,71,79,87,87,100,100];
const makeProfile = (values: number[]): FanProfile => ({
  ...Object.fromEntries(values.map((value, i) => [String((i + 1) * 10), value])),
  fullFanSpeedEnabled: false
});
const DEFAULT_FAN_VALUES = makeProfile(RECOMMENDED);
const initialSlots = (current: FanProfile): Profiles => ({
  '1': { ...current },
  '2': makeProfile([50,55,60,65,75,85,90,95,100,100]),
  '3': makeProfile([60,65,70,75,85,90,95,100,100,100])
});
type FanState = {
  fanProfiles: Profiles;
  quickProfiles: Profiles;
  activeQuickProfile: string;
  fanPerGameProfilesEnabled: boolean;
  customFanCurvesEnabled: boolean;
  supportsCustomFanCurves: boolean;
  saveBusy: boolean;
  saveError: string | null;
};
const initialState: FanState = {
  fanProfiles: { default: { ...DEFAULT_FAN_VALUES } },
  quickProfiles: initialSlots(DEFAULT_FAN_VALUES), activeQuickProfile: '1',
  fanPerGameProfilesEnabled: false, customFanCurvesEnabled: false,
  supportsCustomFanCurves: false, saveBusy: false, saveError: null
};
function rememberSlot(state: FanState) {
  state.quickProfiles[state.activeQuickProfile] = { ...state.fanProfiles.default };
}
export const fanSlice = createSlice({
  name: 'fan', initialState,
  reducers: {
    selectQuickProfile(state, action: PayloadAction<string>) {
      if (!['1', '2', '3'].includes(action.payload)) return;
      state.activeQuickProfile = action.payload;
      state.fanProfiles.default = { ...state.quickProfiles[action.payload] };
      state.fanPerGameProfilesEnabled = false;
      state.customFanCurvesEnabled = true;
    },
    resetRecommended(state) {
      state.fanProfiles.default = makeProfile(RECOMMENDED);
      state.fanPerGameProfilesEnabled = false;
      rememberSlot(state);
    },
    setFanSaveStatus(state, action: PayloadAction<{ busy: boolean; error: string | null }>) {
      state.saveBusy = action.payload.busy;
      state.saveError = action.payload.error;
    },
    setCustomFanCurvesEnabled(state, action: PayloadAction<boolean>) {
      state.customFanCurvesEnabled = action.payload;
    },
    setFanPerGameProfilesEnabled(state, action: PayloadAction<boolean>) {
      state.fanPerGameProfilesEnabled = action.payload;
    },
    setEnableFullFanSpeedMode(state, action: PayloadAction<boolean>) {
      state.fanProfiles.default.fullFanSpeedEnabled = action.payload;
      rememberSlot(state);
    },
    updateFanCurve(state, action: PayloadAction<{ temp: string; fanSpeed: number }>) {
      const temperature = Number(action.payload.temp);
      if (!(temperature in FAN_MINIMUMS) || !Number.isFinite(action.payload.fanSpeed)) return;
      const value = Math.max(FAN_MINIMUMS[temperature], Math.min(100, Math.round(action.payload.fanSpeed)));
      const profile = state.fanProfiles.default;
      for (let t = 10; t <= 100; t += 10) {
        if (t < temperature) profile[String(t)] = Math.min(Number(profile[String(t)]), value);
        else if (t === temperature) profile[String(t)] = value;
        else profile[String(t)] = Math.max(Number(profile[String(t)]), value);
      }
      rememberSlot(state);
    },
    updateFanProfiles(state, action: PayloadAction<Profiles>) { merge(state.fanProfiles, action.payload); }
  },
  extraReducers: builder => {
    builder.addCase(setInitialState, (state, action) => {
      state.fanProfiles = cloneDeep(action.payload.fan || { default: DEFAULT_FAN_VALUES });
      if (!state.fanProfiles.default) state.fanProfiles.default = { ...DEFAULT_FAN_VALUES };
      state.customFanCurvesEnabled = Boolean(action.payload.customFanCurvesEnabled);
      state.fanPerGameProfilesEnabled = Boolean(action.payload.fanPerGameProfilesEnabled);
      state.supportsCustomFanCurves = Boolean(action.payload.supportsCustomFanCurves);
      state.quickProfiles = cloneDeep(action.payload.bazziteFanProfiles || initialSlots(state.fanProfiles.default));
      state.activeQuickProfile = action.payload.bazziteActiveFanProfile || '1';
      state.saveBusy = false;
      state.saveError = null;
    });
  }
});
export const selectSupportsCustomFanCurves = (state: RootState) => state.fan.supportsCustomFanCurves;
export const selectCustomFanCurvesEnabled = (state: RootState) => state.fan.customFanCurvesEnabled;
export const selectFanPerGameProfilesEnabled = (state: RootState) => state.fan.fanPerGameProfilesEnabled;
export const selectActiveFanProfile = (state: RootState): FanProfile =>
  (state.fan.fanPerGameProfilesEnabled && state.fan.fanProfiles[state.ui.currentGameId || 'default']) || state.fan.fanProfiles.default || DEFAULT_FAN_VALUES;
export const selectActiveFanCurve = (state: RootState): Record<string, number> => {
  const profile = selectActiveFanProfile(state);
  return Object.fromEntries(Array.from({ length: 10 }, (_, i) => [String((i + 1) * 10), Number(profile[String((i + 1) * 10)])]));
};
export const selectEnableFullFanSpeedMode = (state: RootState) => Boolean(selectActiveFanProfile(state).fullFanSpeedEnabled);
const mutations: string[] = [
  fanSlice.actions.selectQuickProfile.type, fanSlice.actions.resetRecommended.type,
  fanSlice.actions.updateFanCurve.type, fanSlice.actions.updateFanProfiles.type,
  fanSlice.actions.setEnableFullFanSpeedMode.type, fanSlice.actions.setCustomFanCurvesEnabled.type,
  fanSlice.actions.setFanPerGameProfilesEnabled.type
];
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let saveSequence = 0;
export const saveFanSettingsMiddleware: Middleware<{}, { fan: FanState; ui: { currentGameId?: string } }> = store => next => action => {
  const result = next(action);
  const state = store.getState();
  if (mutations.includes(action.type) || (action.type === setCurrentGameId.type && state.fan.customFanCurvesEnabled)) {
    clearTimeout(saveTimer);
    const sequence = ++saveSequence;
    store.dispatch(fanSlice.actions.setFanSaveStatus({ busy: true, error: null }));
    saveTimer = setTimeout(() => {
      const { fan, ui } = store.getState();
      const gameId = fan.fanPerGameProfilesEnabled ? (ui.currentGameId || 'default') : 'default';
      const info = { fanProfiles: fan.fanProfiles, fanPerGameProfilesEnabled: fan.fanPerGameProfilesEnabled,
        customFanCurvesEnabled: fan.customFanCurvesEnabled, quickProfiles: fan.quickProfiles, activeQuickProfile: fan.activeQuickProfile };
      call<[typeof info, string], boolean>('save_fan_settings', info, gameId).then(success => {
        if (sequence === saveSequence) store.dispatch(fanSlice.actions.setFanSaveStatus({ busy: false, error: success ? null : 'Firmware did not confirm this curve. Check fan support.' }));
      }).catch((error: unknown) => {
        if (sequence === saveSequence) store.dispatch(fanSlice.actions.setFanSaveStatus({ busy: false, error: String(error) }));
      });
    }, 350);
  }
  return result;
};
