"""
Processing of marine LCI data
"""

import yaml
import pandas as pd
import numpy as np
import itertools
from pathlib import Path
from statistics import mean
import re

auth = True
parent_path = Path(__file__).parent
data_path =  parent_path / 'data'

NM_to_KM = 1.852 # km per nautical mile
ANCH_SPEED = 0 # No propulsion used while at anchorage
SM_OPEN = 1.15 # Sea margin for at sea operations (see Propellers Law)
SM_COASTAL = 1.1 # Sea margin for coastal operations (see Propellers Law)
ANCH_TIME = 0.065 # Assumes 6.5% of total time
DEST_MANEUV_SPEED = 3
ORIGIN_MANEUV_SPEED = 5.5

#%% 1. Prepare dataset of marine vessels and routes

with open(data_path / "marine_inputs.yaml", "r") as file:
    marine_inputs = yaml.safe_load(file)

marine_runs0 = pd.read_csv(data_path / 'marine_runs.csv')
distances = pd.read_csv(data_path / 'distances.csv')

# Prepare the engine specs
speeds = (pd.read_csv(data_path / 'engine_characteristics.csv')
          .merge(pd.read_csv(data_path / 'utilization.csv'), how='left',
                 on='Ship Type')
          # Subset the df for relevant ship types
          .query('`Ship Type`.isin(@marine_runs0["Ship Type"])')
          .query('Subtype.isin(@marine_runs0["Subtype"])')
          # .assign(Avg_cruise_draft = lambda x: x['Max Draft (m)'] * 0.6)
          .merge(pd.read_csv(data_path / 'transit_speed_ratios.csv'),
                 how='left', on='Ship Type')
          .assign(Transit_speed = lambda x:
                  x['Max Speed (kn)'] * x['Transit Speed Ratio'])
          .assign(Maneuvering_speed = mean([DEST_MANEUV_SPEED, ORIGIN_MANEUV_SPEED]))
          .assign(Anchorage_speed = ANCH_SPEED)
          # Load = (speed / max speed)^ 3  Propellers Law
          .assign(Transit_load = lambda x:
                  pow(x['Transit_speed'] / x['Max Speed (kn)'], 3))
          .assign(Maneuvering_load = lambda x:
                  pow(x['Maneuvering_speed'] / x['Max Speed (kn)'], 3))
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
                  x['Installed Propulsion Power (kW)'] * x['Transit_load'] * SM_OPEN)
          .assign(Maneuvering_power = lambda x:
                  x['Installed Propulsion Power (kW)'] * x['Maneuvering_load'] * SM_COASTAL)
          .assign(Anchorage_power = lambda x:
                  x['Installed Propulsion Power (kW)'] * x['Anchorage_load'] * SM_COASTAL)
          # ^^ Account for sea margin in the Propellers Law
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


# Calculate time for each run by leg
marine_runs = (marine_runs0
      .merge(distances, how='left', on=['US Region', 'Global Region'])
      .merge(speeds.filter(['Ship Type', 'Subtype', 'Transit_speed']).drop_duplicates(),
             how='left', on=['Ship Type', 'Subtype'])
      .assign(Total_time = lambda x: x['AvgOfDistance (nm)'] / x['Transit_speed'])
      .merge(pd.read_csv(data_path / 'hotel_hours.csv')
             .rename(columns={'Hotel Time': 'Origin_hotel_time'}),
             how='left', on='Global Region')
      .assign(Origin_maneuv_time = lambda x: x['OrigManeuv_Distance'] / ORIGIN_MANEUV_SPEED)
      .assign(Dest_maneuv_time = lambda x: x['DestManeuv_Distance'] / DEST_MANEUV_SPEED)
      .assign(Dest_anchor_time = lambda x: x['Total_time'] * ANCH_TIME)
      .merge(pd.read_csv(data_path / 'hotel_hours_us.csv')
             .rename(columns={'Hotel Time': 'Dest_hotel_time'}),
             how='left', on='Ship Type')
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
        .isin(['Europe', 'Eastern Canada', 'Western Canada',
               'Gulf of Mexico', 'Western Mexico']),
        1, 0)
## TRANSIT ECA based on lookup
marine_runs['Transit_ECA'] = marine_runs['AvgPctECA']


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
df_qa = df.copy()
df = df.drop(columns=df.filter(
    regex=('^.*?(speed|Speed|load|time|Time|Draft|draft|power|'
           'AvgPctECA|Maneuv_Dist).*?')).columns)

#%% 2. Pull in emission factors and generate combined dataset

# Bring in Emission Factors
emissions = (pd.read_csv(data_path / 'emission_factors.csv')
             .melt(id_vars = ['Engine', 'Fuel'],
                   var_name = 'Pollutant',
                   value_name = 'EF')
             )

# Apply speciation
speciation_df = pd.read_csv(data_path / 'flow_speciation.csv')
# Create a mapping from Basis to list of matching Pollutants
pollutant_mapping = {}
for basis in speciation_df['Basis'].unique():
    if basis == 'PM2.5':
        # PM2.5 applies to both PM2.5 ECA and PM2.5 nonECA
        pollutant_mapping[basis] = ['PM25 ECA', 'PM25 nonECA']
    else:
        pollutant_mapping[basis] = [basis]
new_rows = []
for _, emission_row in emissions.iterrows():
    pollutant = emission_row['Pollutant']
    for _, spec_row in speciation_df.iterrows():
        basis = spec_row['Basis']
        if pollutant in pollutant_mapping.get(basis, []):
            new_row = emission_row.copy()
            new_row['Pollutant'] = spec_row['Pollutant']  # Replace with speciated pollutant name
            new_row['EF'] = emission_row['EF'] * spec_row['Fraction']  # Adjust EF
            new_rows.append(new_row)

# Append the new rows to the original emissions dataframe
emissions = pd.concat([emissions, pd.DataFrame(new_rows)], ignore_index=True)

elf = pd.read_csv(data_path / 'engine_load_factor.csv')
elf.columns = ['Pollutant', 'ELF']
## TODO: confirm all the load factors are accounted for
emissions = (emissions
             .merge(elf, how='left', on='Pollutant')
             .assign(ELF = lambda x: x['ELF'].fillna(1.0))
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
      # Drop ECA from the pollutant name, no longer needed
      .assign(Pollutant = lambda x:
              x['Pollutant'].str.replace(r'(ECA|nonECA)', '', regex=True).str.strip())
      .assign(EF_Unit = 'g / kWh')
      .assign(Energy = lambda x: x[[f'{c}_energy' for c in legs]].sum(axis=1))
      .assign(FlowTotal = lambda x: x['EF'] * x['Energy'] / 1000)
      .assign(Unit = 'kg')
      .drop(columns=df.filter(regex='^.*?(energy).*?').columns)
      # Add tons for validation to original file
      .assign(tons = lambda x: x['FlowTotal'] * .00110231)
      )


## Assign specific contexts based on the leg
## TODO: also consider locations? Destination for anchorage, maneuv and hotel
# should be assigned to US, while the origin should be assigned to foreign country?
# Transit emissions are unassigned and/or GLO? May need to maintain dest/origin
# designation which are dropped by now
df = (df
      .assign(Context = lambda x: x.apply(
          lambda row: "/".join([row['Zone'], row['Leg']]), axis=1))
      )

df_qa2 = df.copy()
## Drop unneccesary fields
df = df.drop(columns=['Engine Category', 'Engine Type',
                      'Installed Propulsion Power (kW)',
                      'EF', 'ELF', 'EF_Unit'])

#%% 3. Align elementary flows with FEDEFL
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
from flcac_utils.util import round_to_sig_figs
mapped_df = (mapped_df
             .assign(FlowAmount = lambda x: x['FlowTotal'] /
                     (x['AvgOfDistance (nm)'] * NM_to_KM * x['Capacity (metric tons)']
                      * x['Utilization'].fillna(1)))
    )

#%% Extract fuel information
from flcac_utils.mapping import prepare_tech_flow_mappings

## Identify mappings for technosphere flows (fuel inputs)
fuel_df = pd.read_csv(data_path / 'Marine_fuel_mapping.csv')

fuel_dict, flow_objs, provider_dict = prepare_tech_flow_mappings(fuel_df, auth=auth)

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
           # .assign(ProcessName = lambda x: (
           #     'Transport; ' + x['Ship Type'].str.lower() + '; '
           #     + (x['Fuel'].str.lower()) + ' powered; ' + x['Global Region']
           #     + ' to ' + x['US Region']))
           .assign(ProcessName = lambda x: (
               'Transport, ' + x['Ship Type'].str.lower() + ', '
               + (x['Fuel'].str.lower()) + ' powered, ' + x['Global Region']
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
                   # x['ProcessName'].str.rsplit(';', n=1).str.get(0),
                   x['FlowName']))
           .assign(Context = np.where(cond1, marine_inputs['FlowContext'],
                   df_olca['Context']))
           .assign(FlowUUID = lambda x: np.where(cond1,
                   x.apply(lambda z: make_uuid(z['FlowName'], z['Context']), axis=1),
                   x['FlowUUID']))
           # For fuel values assign fuel as the FlowName
           .assign(FlowName = lambda x: np.where(cond2, x['Fuel'], x['FlowName']))
           )

#%% Apply fuel mapping data
from flcac_utils.mapping import apply_tech_flow_mapping

df_olca = apply_tech_flow_mapping(df_olca.rename(columns={'FlowName':'name',
                                                          'FlowAmount':'amount',
                                                          'Unit':'unit'}),
                                  fuel_dict, flow_objs, provider_dict)

## TODO: fuel consumption has dropped dramatically compared to old data need to
# do a carbon comparison;
# based on some checks it seems that the amount of fuel in the old processes is too high
# given the reported CO2 emissions, and that the CO2 content relative to fuel consumed
# is more appropriate in the new data

df_olca = (df_olca
           .query('not(FlowUUID.isna())')
           .drop(columns=['bridge'], errors='ignore')
           )
df_bridge = pd.DataFrame()
# df_olca.to_csv(parent_path /'marine_processed_output.csv', index=False)

from flcac_utils.generate_processes import build_flow_dict
flows, new_flows = build_flow_dict(
    pd.concat([df_olca, df_bridge], ignore_index=True))
# pass bridge processes too to ensure those flows get created

# replace newly created flows with those pulled via API
api_flows = {flow.id: flow for k, flow in flow_objs.items()}
if not(flows.keys() | api_flows.keys()) == flows.keys():
    print('Warning, some flows not consistent')
else:
    flows.update(api_flows)

#%% Assign exchange dqi
from flcac_utils.util import format_dqi_score, increment_dqi_value
df_olca['exchange_dqi'] = format_dqi_score(marine_inputs['DQI']['Flow'])
# drop DQI entry for reference flow
df_olca['exchange_dqi'] = np.where(df_olca['reference'] == True,
                                    '', df_olca['exchange_dqi'])

#%% Aggregate

df_olca = df_olca.drop(columns=['Energy', 'FlowTotal', 'tons',
                                 'Zone', 'Leg', 'Engine',
                                 'AvgOfDistance (nm)'])
df_olca = (df_olca
           .groupby([c for c in df_olca if c not in ['FlowAmount', 'amount']],
                    dropna=False)
           .agg('sum')
           .reset_index()
           )
df_olca['amount'] = df_olca['amount'].apply(lambda x: round_to_sig_figs(x, 4))

#%% prepare metadata
from flcac_utils.generate_processes import build_location_dict
from flcac_utils.util import assign_year_to_meta, \
    extract_actors_from_process_meta, extract_dqsystems,\
    extract_sources_from_process_meta, generate_locations_from_exchange_df

with open(data_path / 'Marine_process_metadata.yaml') as f:
    process_meta = yaml.safe_load(f)

process_meta = assign_year_to_meta(process_meta, marine_inputs['Year'])
process_meta['time_description'] = (process_meta['time_description']
                                    .replace('[YEAR]', str(marine_inputs['Year']))
                                    )
(process_meta, source_objs) = extract_sources_from_process_meta(
    process_meta, bib_path = data_path / 'transport.bib')
(process_meta, actor_objs) = extract_actors_from_process_meta(process_meta)
dq_objs = extract_dqsystems(marine_inputs['DQI']['dqSystem'])
process_meta['dq_entry'] = format_dqi_score(marine_inputs['DQI']['Process'])

# prepare locations
# locations = generate_locations_from_exchange_df(df_olca)
# location_objs = build_location_dict(df_olca, locations)

#%% Build json file
from flcac_utils.generate_processes import \
    build_process_dict, write_objects, validate_exchange_data

validate_exchange_data(df_olca)

processes = {}
# loop through each vehicle type and region to adjust metadata before writing processes
for s in df_olca['Ship Type'].unique():
    _df_olca = df_olca.query('`Ship Type` == @s')
    # vehicle_desc = process_meta['vehicle_descriptions'].get(
    #     re.sub(r'[^a-zA-Z0-9]', '_', s.replace(',','')))
    for f in _df_olca['Fuel'].unique():
        _process_meta = process_meta.copy()
        for k, v in _process_meta.items():
            if not isinstance(v, str): continue
            v = v.replace('[SHIP_TYPE]', s.title())
            v = v.replace('[FUEL]', f)
            _process_meta[k] = v
        p_dict = build_process_dict(_df_olca.query('Fuel == @f'),
                                    flows, meta=_process_meta,
                                       # loc_objs=location_objs,
                                       source_objs=source_objs,
                                       actor_objs=actor_objs,
                                       dq_objs=dq_objs,
                                       )
        processes.update(p_dict)
# build bridge processes
bridge_processes = build_process_dict(df_bridge, flows, meta=marine_inputs['Bridge'])

#%% Write to json
out_path = parent_path / 'output'
write_objects('marine', flows, new_flows, processes,
              source_objs, actor_objs, dq_objs,
              # location_objs, bridge_processes,
              out_path = out_path)
## ^^ Import this file into an empty database with units and flow properties only
## or merge into USLCI and overwrite all existing datasets

#%% Unzip files to repo
from flcac_utils.util import extract_latest_zip

extract_latest_zip(out_path,
                   parent_path,
                   output_folder_name = Path('output') / 'marine_v1.0.0')
