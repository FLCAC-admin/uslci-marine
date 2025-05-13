"""
Processing of marine LCI data
"""

import yaml
import pandas as pd
import numpy as np
import itertools
from pathlib import Path
import re

auth = True
parent_path = Path(__file__).parent
data_path =  parent_path / 'data'

#%% Prepare dataset of marine emissions

## Check Teams (Task 3 Transportation Datasets / Marine) for the latest data
marine_runs = pd.read_csv(data_path / 'marine_runs.csv')
distances = pd.read_csv(data_path / 'distances.csv')

# Prepare the engine specs
speeds = (pd.read_csv(data_path / 'engine_characteristics.csv')
          .query('`Ship Type`.isin(@marine_runs["Ship Type"])') # Simplify for now
          .assign(Cruise_speed = lambda x: x['Max Speed (kn)'] * 0.75)
          .assign(Avg_cruise_draft = lambda x: x['Max Draft (m)'] * 0.6)
          .merge(pd.read_csv(data_path / 'transit_speed_ratios.csv'), how='left', on='Ship Type')
          .assign(Transit_speed = lambda x: x['Max Speed (kn)'] * x['Mode of Transit Speed Ratios'])
          .assign(Transit_load = lambda x: pow(x['Transit_speed'] / x['Max Speed (kn)'], 3))
          .assign(Maneuvering_speed = 4) # TODO: update
          .assign(Maneuvering_load = lambda x: pow(x['Maneuvering_speed'] / x['Max Speed (kn)'], 3))
          .assign(Anchorage_speed = 2) # TODO: update
          .assign(Anchorage_load = lambda x: pow(x['Anchorage_speed'] / x['Max Speed (kn)'], 3))
          )

# Duplicate the dataframe for the other engine types and merge in those loads
speeds2 = (
    pd.DataFrame(np.repeat(speeds.values, 2, axis=0), columns=speeds.columns)
          .assign(Engine = np.tile(['Auxiliary', 'Boiler'], len(speeds))))
speeds2 = (speeds2
          .merge(pd.read_csv(data_path / 'auxiliary_load.csv').assign(Engine = 'Auxiliary'),
                 how='left', on=['Ship Type', 'Subtype', 'Engine'])
          .merge(pd.read_csv(data_path / 'boiler_load.csv').assign(Engine = 'Boiler'),
                 how='left', on=['Ship Type', 'Subtype', 'Engine'],
                 suffixes = ('', '_')))
cols = ['Transit (kW)', 'Maneuvering (kW)', 'Hotelling (kW)', 'Anchorage (kW)']
for col in cols:
    speeds2[col] = speeds2[col].fillna(speeds2[f'{col}_'])
speeds2 = speeds2.drop(columns=speeds2.filter(regex='_$').columns)

# Calculate power for each engine type
speeds = (pd.concat([
    (speeds
          .assign(Transit_power = lambda x: x['Installed Propulsion Power (kW)'] * x['Transit_load'] * 1.15)
          .assign(Maneuvering_power = lambda x: x['Installed Propulsion Power (kW)'] * x['Maneuvering_load'] * 1.1)
          .assign(Anchorage_power = lambda x: x['Installed Propulsion Power (kW)'] * x['Anchorage_load'] * 1.1)
          .assign(Port_power = 0)
          .assign(Engine = 'Main')),
     speeds2], ignore_index=True)
    .assign(Transit_power = lambda x: x['Transit_power'].fillna(x['Transit (kW)']))
    .assign(Maneuvering_power = lambda x: x['Maneuvering_power'].fillna(x['Maneuvering (kW)']))
    .assign(Anchorage_power = lambda x: x['Anchorage_power'].fillna(x['Anchorage (kW)']))
    .assign(Port_power = lambda x: x['Port_power'].fillna(x['Hotelling (kW)']))
    .drop(columns=cols)
    )
del(speeds2)


US_HOTEL = 34.6
# Calculate time for each run by leg
marine_runs = (marine_runs
      .merge(distances, how='left', on=['US Region', 'Global Region'])
      .merge(speeds.filter(['Ship Type', 'Subtype', 'Cruise_speed']).drop_duplicates(),
             how='left', on=['Ship Type', 'Subtype'])
      .assign(Total_time = lambda x: x['AvgOfDistance (nm)'] / x['Cruise_speed'])
      .merge(pd.read_csv(data_path / 'hotel_hours.csv')
             .rename(columns={'Hotel Time': 'Origin Hotel Time'}),
             how='left', on='Global Region')
      .assign(Origin_maneuv_time = 5) # ASSUMPTION
      .assign(Dest_maneuv_time = 5) # ASSUMPTION
      .assign(Dest_anchor_time = 5) # ASSUMPTION
      .assign(Dest_hotel_time = US_HOTEL)
      .assign(Transit_time = lambda x: x['Total_time'] - x['Origin_maneuv_time'] - x['Dest_maneuv_time'])
      .assign(Anchorage_time = lambda x: x['Dest_anchor_time'])
      .assign(Maneuvering_time = lambda x: x['Origin_maneuv_time'] + x['Dest_maneuv_time'])
      .assign(Port_time = lambda x: x['Origin Hotel Time'] + x['Dest_hotel_time'])
      )


legs = ['Transit', 'Anchorage', 'Maneuvering', 'Port']
engines = ['Main', 'Auxiliary', 'Boiler']
## TODO implement ECA vs nonECA splits
# zones = ['ECA', 'nonECA']
zones = ['All']

# Combine all permutations and calculate energy use by leg and engine
df = (marine_runs
       .merge(pd.DataFrame(list(itertools.product(legs, engines, zones)),
                           columns=['Leg', 'Engine', 'Zone']),
              how='cross')
       .merge(speeds, how='left', on=['Ship Type', 'Subtype', 'Engine'])
       )
for l in legs:
    df[f'{l}_energy'] = np.where(
        df['Leg'] == l, df[f'{l}_time'] * df[f'{l}_power'], 0)
df = df.drop(columns=df.filter(regex='^.*?(speed|Speed|load|time|Time|Draft|draft|power).*?').columns)

# Bring in Emission Factors
emissions = (pd.read_csv(data_path / 'emission_factors.csv')
             .melt(id_vars = ['Engine', 'Fuel'],
                   var_name = 'Pollutant',
                   value_name = 'EF')
             )
elf = pd.read_csv(data_path / 'engine_load_factor.csv')
elf.columns = ['Pollutant', 'ELF']
## TODO: confirm all the load factors are accounted for
emissions = (emissions
             .merge(elf, how='left', on='Pollutant')
             .assign(ELF = lambda x: x['ELF'].fillna(1))
             )

## TODO: split out ECA and nonECA
df = (df
      .merge(emissions, how='left', on=['Engine', 'Fuel'])
      .assign(ELF = lambda x: np.where(x['Leg'].isin(['Transit', 'Port']), 1,
                                       x['ELF']))
      ## ^^ ELF only applies to Anchorage or Maneuvering
      .assign(EF_Unit = 'g / kWh')
      .assign(Energy = lambda x: x[[f'{c}_energy' for c in legs]].sum(axis=1))
      .assign(FlowAmount = lambda x: x['EF'] * x['Energy'] / 1000)
      .assign(Unit = 'kg')
      .drop(columns=df.filter(regex='^.*?(energy).*?').columns)
      .assign(tons = lambda x: x['FlowAmount'] * .00110231)
      )

