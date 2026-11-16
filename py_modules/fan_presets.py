"""Three editable, persistent global fan-curve slots for the Bazzite fork."""
from copy import deepcopy
from collections.abc import Mapping
try:
    from . import fan_control
except ImportError:
    import fan_control

RECOMMENDED = (44,48,55,60,71,79,87,87,100,100)
COOLER = (50,55,60,65,75,85,90,95,100,100)
STRONG = (60,65,70,75,85,90,95,100,100,100)
SLOTS = ('1','2','3')

def make_profile(values):
    return {**{str(t):v for t,v in zip(range(10,101,10), values)},
            'fullFanSpeedEnabled':False}

def validate_slots(profiles, active):
    if not isinstance(profiles, Mapping) or set(profiles) != set(SLOTS) or active not in SLOTS:
        raise ValueError('Exactly three fan profiles and a valid active slot are required')
    for profile in profiles.values():
        fan_control.parse_fan_profile(profile)
        if type(profile.get('fullFanSpeedEnabled',False)) is not bool:
            raise ValueError('Full fan speed must be boolean')
    return deepcopy(dict(profiles)), active

def initial_state(saved):
    profiles = saved.get('bazziteFanProfiles')
    if profiles is not None:
        return validate_slots(profiles, saved.get('bazziteActiveFanProfile','1'))
    current = (saved.get('fan') or {}).get('default') or make_profile(RECOMMENDED)
    fan_control.parse_fan_profile(current)
    return {'1':deepcopy(current),'2':make_profile(COOLER),'3':make_profile(STRONG)}, '1'
