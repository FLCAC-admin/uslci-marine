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

NM_to_KM = 1.852 # km per nautical mile

#%% Prepare dataset of marine emissions

with open(data_path / "marine_inputs.yaml", "r") as file:
    marine_inputs = yaml.safe_load(file)

## Check Teams (Task 3 Transportation Datasets / Marine) for the latest data
marine_runs0 = pd.read_csv(data_path / 'marine_runs.csv')
distances = pd.read_csv(data_path / 'distances.csv')

# Prepare the engine specs
speeds = (pd.read_csv(data_path / 'engine_characteristics.csv')
          .query('`Ship Type`.isin(@marine_runs0["Ship Type"])') # Simplify for now
          .assign(Cruise_speed = lambda x: x['Max Speed (kn)'] * 0.75)
          .assign(Avg_cruise_draft = lambda x: x['Max Draft (m)'] * 0.6)
          .merge(pd.read_csv(data_path / 'transit_speed_ratios.csv'),
                 how='left', on='Ship Type')
          .assign(Transit_speed = lambda x:
                  x['Max Speed (kn)'] * x['Mode of Transit Speed Ratios'])
          .assign(Transit_load = lambda x:
                  pow(x['Transit_speed'] / x['Max Speed (kn)'], 3))
          .assign(Maneuvering_speed = 4) # TODO: update
          .assign(Maneuvering_load = lambda x:
                  pow(x['Maneuvering_speed'] / x['Max Speed (kn)'], 3))
          .assign(Anchorage_speed = 2) # TODO: update
          .assign(Anchorage_load = lambda x:
                  pow(x['Anchorage_speed'] / x['Max Speed (kn)'], 3))
          )

# Duplicate the dataframe for the other engine types and merge in those loads
speeds2 = (
    pd.DataFrame(np.repeat(speeds.values, 2, axis=0), columns=speeds.columns)
          .assign(Engine = np.tile(['Auxiliary', 'Boiler'], len(speeds))))
speeds2 = (speeds2
          .merge(pd.read_csv(data_path / 'auxiliary_load.csv')
                 .assign(Engine = 'Auxiliary'),
                 how='left', on=['Ship Type', 'Subtype', 'Engine'])
          .merge(pd.read_csv(data_path / 'boiler_load.csv')
                 .assign(Engine = 'Boiler'),
                 how='left', on=['Ship Type', 'Subtype', 'Engine'],
                 suffixes = ('', '_')))
cols = ['Transit (kW)', 'Maneuvering (kW)', 'Hotelling (kW)', 'Anchorage (kW)']
for col in cols:
    speeds2[col] = speeds2[col].fillna(speeds2[f'{col}_'])
speeds2 = speeds2.drop(columns=speeds2.filter(regex='_$').columns)

# Calculate power for each engine type
speeds = (pd.concat([
    (speeds
          .assign(Transit_power = lambda x:
                  x['Installed Propulsion Power (kW)'] * x['Transit_load'] * 1.15)
          .assign(Maneuvering_power = lambda x:
                  x['Installed Propulsion Power (kW)'] * x['Maneuvering_load'] * 1.1)
          .assign(Anchorage_power = lambda x:
                  x['Installed Propulsion Power (kW)'] * x['Anchorage_load'] * 1.1)
          .assign(Port_power = 0)
          .assign(Engine = 'Main')),
     speeds2], ignore_index=True)
    .assign(Transit_power = lambda x:
            x['Transit_power'].fillna(x['Transit (kW)']))
    .assign(Maneuvering_power = lambda x:
            x['Maneuvering_power'].fillna(x['Maneuvering (kW)']))
    .assign(Anchorage_power = lambda x:
            x['Anchorage_power'].fillna(x['Anchorage (kW)']))
    .assign(Port_power = lambda x:
            x['Port_power'].fillna(x['Hotelling (kW)']))
    .drop(columns=cols)
    )
del(speeds2)


US_HOTEL = 34.6
# Calculate time for each run by leg
marine_runs = (marine_runs0
      .merge(distances, how='left', on=['US Region', 'Global Region'])
      .merge(speeds.filter(['Ship Type', 'Subtype', 'Cruise_speed']).drop_duplicates(),
             how='left', on=['Ship Type', 'Subtype'])
      .assign(Total_time = lambda x: x['AvgOfDistance (nm)'] / x['Cruise_speed'])
      .merge(pd.read_csv(data_path / 'hotel_hours.csv')
             .rename(columns={'Hotel Time': 'Origin_hotel_time'}),
             how='left', on='Global Region')
      .assign(Origin_maneuv_time = 5) # ASSUMPTION
      .assign(Dest_maneuv_time = 5) # ASSUMPTION
      .assign(Dest_anchor_time = 5) # ASSUMPTION
      .assign(Dest_hotel_time = US_HOTEL)
      .assign(Transit_time = lambda x:
              x['Total_time'] - x['Origin_maneuv_time'] - x['Dest_maneuv_time'])
      )

legs = ['Transit', 'Anchorage', 'Maneuvering', 'Port']
engines = ['Main', 'Auxiliary', 'Boiler']
zones = ['ECA', 'nonECA']

## Assign ECA ratios and calculate total time
for l in [x for x in legs if x != 'Transit']:
    marine_runs[f'Dest_{l}_ECA'] = 1 # US is in ECA
    marine_runs[f'Origin_{l}_ECA'] = np.where(
        marine_runs['Global Region']
        .isin(['Europe', 'Eastern Canada', 'Western Canada']),
        1, 0)
marine_runs['Transit_ECA'] = 0

marine_runs = (marine_runs
      .merge(pd.DataFrame(zones, columns=['Zone']), how='cross')
      .assign(Anchorage_time = lambda x: np.where(x['Zone'] == 'ECA',
              x['Dest_anchor_time'] * x['Dest_Anchorage_ECA'],
              x['Dest_anchor_time'] * (1-x['Dest_Anchorage_ECA'])))
      .assign(Maneuvering_time = lambda x: np.where(x['Zone'] == 'ECA',
              x['Origin_maneuv_time'] * x['Origin_Maneuvering_ECA']
              + x['Dest_maneuv_time'] * x['Dest_Maneuvering_ECA'],
              x['Origin_maneuv_time'] * (1-x['Origin_Maneuvering_ECA'])
              + x['Dest_maneuv_time'] * (1-x['Dest_Maneuvering_ECA'])))
      .assign(Port_time = lambda x: np.where(x['Zone'] == 'ECA',
              x['Origin_hotel_time'] * x['Origin_Port_ECA']
              + x['Dest_hotel_time'] * x['Dest_Port_ECA'],
              x['Origin_hotel_time'] * (1-x['Origin_Port_ECA'])
              + x['Dest_hotel_time'] * (1-x['Dest_Port_ECA'])))
      .assign(Transit_time = lambda x: np.where(x['Zone'] == 'ECA',
              x['Transit_time'] * x['Transit_ECA'],
              x['Transit_time'] * (1-x['Transit_ECA'])))
      .drop(columns = marine_runs.filter(regex='^.*?(_ECA).*?').columns)
      )

# Combine all permutations and calculate energy use by leg and engine
df = (marine_runs
       .merge(pd.DataFrame(list(itertools.product(legs, engines)),
                           columns=['Leg', 'Engine']),
              how='cross')
       .merge(speeds, how='left', on=['Ship Type', 'Subtype', 'Engine'])
       )
for l in legs:
    df[f'{l}_energy'] = np.where(
        df['Leg'] == l, df[f'{l}_time'] * df[f'{l}_power'], 0)
df = df.drop(columns=df.filter(
    regex='^.*?(speed|Speed|load|time|Time|Draft|draft|power).*?').columns)

#%% Generate combined dataset

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

df = (df
      .merge(emissions, how='left', on=['Engine', 'Fuel'])
      .assign(ELF = lambda x: np.where(x['Leg'].isin(['Transit', 'Port']), 1,
                                       x['ELF']))
      ## ^^ ELF only applies to Anchorage or Maneuvering
      .assign(description = lambda x:
              np.select([x['Pollutant'].str.contains(' ECA'),
                         x['Pollutant'].str.contains('nonECA')],
                        ['ECA', 'nonECA'], default=''))
      .query('~(description == "ECA" and Zone == "nonECA")')
      .query('~(description == "nonECA" and Zone == "ECA")')
      .assign(EF_Unit = 'g / kWh')
      .assign(Energy = lambda x: x[[f'{c}_energy' for c in legs]].sum(axis=1))
      .assign(FlowTotal = lambda x: x['EF'] * x['Energy'] / 1000)
      .assign(Unit = 'kg')
      .drop(columns=df.filter(regex='^.*?(energy).*?').columns)
      .assign(tons = lambda x: x['FlowTotal'] * .00110231)
      )


## Assign specific contexts based on the leg
## TODO: also consider locations?
df = (df
      .assign(Context = lambda x: x.apply(
          lambda row: "/".join([row['Zone'], row['Leg']]), axis=1))
      )

## Drop unneccesary fields
df = df.drop(columns=['Engine Category', 'Engine Type',
                      'Installed Propulsion Power (kW)',
                      'EF', 'ELF', 'EF_Unit'])

#%% Align elementary flows with FEDEFL
from esupy.mapping import apply_flow_mapping
from esupy.util import make_uuid

kwargs = {}
kwargs['material_crosswalk'] = (data_path /
                                'Marine_fedefl_flow_mapping.csv')
## ^^ hack to pass a local mapping file

mapped_df = apply_flow_mapping(
    df=df, source=None, flow_type='ELEMENTARY_FLOW',
    keep_unmapped_rows=True, ignore_source_name=True,
    field_dict = {
        'SourceName': '',
        'FlowableName': 'Pollutant',
        'FlowableUnit': 'Unit',
        'FlowableContext': 'Context',
        'FlowableQuantity': 'FlowTotal',
        'UUID': 'FlowUUID'},
    **kwargs
    ).rename(columns={'Pollutant': 'FlowName'})

#%% Convert to reference unit
mapped_df = (mapped_df
             .assign(FlowAmount = lambda x: x['FlowTotal'] /
                     (x['AvgOfDistance (nm)'] * NM_to_KM * x['Capacity (metric tons)']))
    )

#%% Update the reference_flow_var for each process
df_olca = pd.concat([mapped_df,
                     (df[['US Region', 'Global Region', 'Fuel', 'Ship Type',
                          'Subtype']]
                      .drop_duplicates()
                      .assign(reference = True)
                      .assign(IsInput = False)
                      .assign(FlowAmount = 1)
                      .assign(FlowName = 'reference_flow_var')
                      .assign(description = '')
                      )], ignore_index=True)

cond1 = df_olca['FlowName'] == 'reference_flow_var'
cond2 = df_olca['FlowName'] == marine_inputs['EnergyFlow']

df_olca = (df_olca
           .assign(ProcessName = lambda x: ('Transport, ' + x['Ship Type'] + ', '
                                            + (x['Fuel'].str.lower())
                                            + ' powered, ' + x['Global Region']
                                            + ' to ' + x['US Region']))
           .assign(ProcessCategory = marine_inputs.get('ProcessContext'))
           .assign(ProcessID = lambda x: x['ProcessName'].apply(make_uuid))
           .assign(reference = np.where(cond1, True, False))
           .assign(IsInput = np.where(cond2, True, False))
           .assign(FlowType = np.where(cond1 | cond2, 'PRODUCT_FLOW',
                   'ELEMENTARY_FLOW'))
           .assign(Unit = np.where(cond1, 't*km', df_olca['Unit']))
           .assign(FlowName = lambda x: np.where(cond1,
                   x['ProcessName'].str.rsplit(',', n=1).str.get(0),
                   x['FlowName']))
           .assign(Context = np.where(cond1, marine_inputs['FlowContext'],
                   df_olca['Context']))
           .assign(FlowUUID = lambda x: np.where(cond1,
                   x.apply(lambda z: make_uuid(z['FlowName'], z['Context']), axis=1),
                   x['FlowUUID']))
           )
