import { Field, PanelSectionRow, SliderField } from '@decky/ui';
import { useDispatch, useSelector } from 'react-redux';
import { FAN_MINIMUMS, fanSlice, selectActiveFanCurve } from '../../redux-modules/fanSlice';

const TEMPERATURES = Array.from({ length: 10 }, (_, index) => (index + 1) * 10);

export default function FanCurveSliders() {
  const curve = useSelector(selectActiveFanCurve);
  const dispatch = useDispatch();
  return <>
    {TEMPERATURES.map(temperature => (
      <PanelSectionRow key={temperature}>
        {temperature >= 90
          ? <Field label={`${temperature} °C`}>100% · protected</Field>
          : <SliderField
              label={`${temperature} °C · ${curve[String(temperature)]}%`}
              value={curve[String(temperature)]}
              min={FAN_MINIMUMS[temperature]}
              max={100}
              step={1}
              minimumDpadGranularity={1}
              showValue={false}
              editableValue={false}
              validValues="range"
              onChange={value => dispatch(fanSlice.actions.updateFanCurve({
                temp: String(temperature), fanSpeed: Math.round(value)
              }))}
            />}
      </PanelSectionRow>
    ))}
  </>;
}
