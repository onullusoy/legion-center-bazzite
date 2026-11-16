import { ButtonItem, Field, Focusable, PanelSection, PanelSectionRow, staticClasses } from '@decky/ui';
import { definePlugin } from '@decky/api';
import { FC, memo, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Provider, useDispatch, useSelector } from 'react-redux';
import { getSettings } from './backend/utils';
import { currentGameIdListener } from './backend/currentGameIdListener';
import { store } from './redux-modules/store';
import { getInitialLoading } from './redux-modules/uiSlice';
import { setInitialState } from './redux-modules/extraActions';
import PowerLedPanel from './components/PowerLedPanel';
import AcpiCallPanel from './components/AcpiCallPanel';
import FanPanel from './components/fan/FanPanel';
import ErrorBoundary from './components/ErrorBoundary';
import VersionPanel from './components/OtaUpdates';
import CommunityFeatures from './components/CommunityFeatures';
import ChargePanel from './components/ChargePanel';
import { GyroPanel, TouchpadPanel } from './components/ControllerPanel';
import { FanAutomationPanel, NightModePanel, ResumeHealthPanel, SleepHistoryPanel } from './components/AutomationPanel';
import logo from '../assets/Icon.png';

type Page = 'home' | 'fan' | 'lighting' | 'power' | 'controller' | 'system' |
  'awakeLed' | 'sleepLed' | 'rgb' | 'night' | 'charge' | 'automation' | 'sleepHistory' |
  'touchpad' | 'gyro' | 'diagnostics' | 'resume' | 'support';
const PARENTS: Partial<Record<Page, Page>> = {
  fan:'home', lighting:'home', power:'home', controller:'home', system:'home',
  awakeLed:'lighting', sleepLed:'lighting', rgb:'lighting', night:'lighting',
  charge:'power', automation:'power', sleepHistory:'power',
  touchpad:'controller', gyro:'controller', diagnostics:'system', resume:'system', support:'system'
};
const TITLES: Record<Page, string> = {
  home:'Device settings', fan:'Fan Control', lighting:'Lighting', power:'Battery & Power',
  controller:'Controller', system:'System', awakeLed:'Power button LED', sleepLed:'Sleep LED',
  rgb:'Joystick RGB', night:'Night mode', charge:'Charge limit', automation:'Automatic fan profiles',
  sleepHistory:'Sleep battery use', touchpad:'Touchpad pointer', gyro:'Gyro test',
  diagnostics:'Diagnostics', resume:'Resume health', support:'Fan support'
};

const Content: FC = memo(() => {
  const loading = useSelector(getInitialLoading);
  const dispatch = useDispatch();
  const [page, setPage] = useState<Page>('home');
  const pageRoot = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    let parent = pageRoot.current?.parentElement;
    while (parent) {
      if (parent.scrollHeight > parent.clientHeight) {
        parent.scrollTop = 0;
        break;
      }
      parent = parent.parentElement;
    }
  }, [page]);
  useEffect(() => {
    if (!['fan', 'awakeLed', 'charge'].includes(page)) return;
    let active = true;
    getSettings().then(settings => { if (active) dispatch(setInitialState(settings)); }).catch(() => {});
    return () => { active = false; };
  }, [page, dispatch]);
  if (loading) return <PanelSection><PanelSectionRow><Field label="Status">Loading device settings…</Field></PanelSectionRow></PanelSection>;
  const navigate = (target: Page) => <PanelSectionRow key={target}>
    <ButtonItem layout="below" onClick={() => setPage(target)}>{TITLES[target]}</ButtonItem>
  </PanelSectionRow>;
  const submenu = (items: Page[]) => <PanelSection title={TITLES[page]}>{items.map(navigate)}</PanelSection>;
  let content;
  switch (page) {
    case 'home': content = <>{submenu(['fan', 'lighting', 'power', 'controller', 'system'])}<VersionPanel /></>; break;
    case 'fan': content = <FanPanel />; break;
    case 'lighting': content = <>
      <PowerLedPanel />
      <CommunityFeatures view="lighting" />
      <NightModePanel />
    </>; break;
    case 'power': content = <><ChargePanel />{submenu(['automation', 'sleepHistory'])}</>; break;
    case 'controller': content = submenu(['touchpad', 'gyro']); break;
    case 'system': content = submenu(['diagnostics', 'resume', 'support']); break;
    case 'awakeLed': content = <PowerLedPanel />; break;
    case 'sleepLed': content = <CommunityFeatures view="sleep" />; break;
    case 'rgb': content = <CommunityFeatures view="rgb" />; break;
    case 'night': content = <NightModePanel />; break;
    case 'charge': content = <ChargePanel />; break;
    case 'automation': content = <FanAutomationPanel />; break;
    case 'sleepHistory': content = <SleepHistoryPanel />; break;
    case 'touchpad': content = <TouchpadPanel />; break;
    case 'gyro': content = <GyroPanel />; break;
    case 'diagnostics': content = <CommunityFeatures view="diagnostics" />; break;
    case 'resume': content = <ResumeHealthPanel />; break;
    case 'support': content = <AcpiCallPanel />; break;
  }
  const back = () => { setPage(PARENTS[page] || 'home'); };
  return <Focusable ref={pageRoot} key={page} flow-children="column" noFocusRing
    onCancel={page === 'home' ? undefined : event => { event.preventDefault(); event.stopPropagation(); back(); }}
    onCancelActionDescription={page === 'home' ? undefined : 'Back'}>
    {page !== 'home' && <PanelSection><PanelSectionRow><ButtonItem layout="below" onClick={back}>‹ Back</ButtonItem></PanelSectionRow></PanelSection>}
    <ErrorBoundary key={page} title={TITLES[page]}>{content}</ErrorBoundary>
  </Focusable>;
});

const AppContainer: FC = () => <Provider store={store}><Content /></Provider>;
export default definePlugin(() => {
  getSettings().then(settings => store.dispatch(setInitialState(settings || {})))
    .catch(error => console.error('Legion Center: settings could not be loaded', error));
  const clearListener = currentGameIdListener();
  return {
    name:'Legion Center',
    titleView:<div className={staticClasses.Title}>Legion Center · Bazzite</div>,
    content:<AppContainer />,
    icon:<img src={logo} style={{width:'1rem',filter:'invert(100%) sepia(0%) saturate(2%) hue-rotate(157deg) brightness(107%) contrast(101%)'}} />,
    onDismount() { clearListener(); }
  };
});
