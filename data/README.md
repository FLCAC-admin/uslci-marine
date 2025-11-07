# Input Data for USLCI-Marine

- [Engine characteristics](engine_characteristics.csv): Main engine size, max speed, and type
by vessel. Source: [EPA 2022, Table C.3](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)

- [Auxiliary load](auxiliary_load.csv) and [Boiler load](boiler_load.csv): Engine
size by vessel and by leg. Source: [EPA 2022, Table E.1 and E.2](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)

- [Brake Specific Fuel Consumption](BFSC.csv): Brake Specific Fuel Consumption. Source: [EPA 2022, Table 3.6](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)
  

- [Distances](distances.csv): Distance between typical ports by region in nautical
miles.  Calcuated by mapping shipping lanes and typical routes from Entrance and Clearance including emission control areas. Sources [ArcGIS, 2013](https://www.arcgis.com/home/item.html?id=12c0789207e64714b9545ad30fca1633), [NDC, 2023](https://ndclibrary.sec.usace.army.mil/resource?title=Vessel%20Entrances%20and%20Clearances%20-%202023&documentId=5c8077e4-23a6-4cb2-e9a5-86272e6fd2ca0), and [IMO](https://www.imo.org/en/ourwork/environment/pages/emission-control-areas-(ecas)-designated-under-regulation-13-of-marpol-annex-vi-(nox-emission-control).aspx)

- [Emission factors](emission_factors.csv): Emission factors in g/kWh by engine type
and fuel. Source: [EPA 2024, Table 11](https://gaftp.epa.gov/air/emismod/2022/v1/reports/mobile/CMV/2022%20C3%20Marine%20Emissions%20Tool%20%20Documentation.pdf) and [EPA 2022, Equations 3.3, 3.4, and 3.5 and Tables 3.6 (averaged), 3.8, and 3.9](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)

- [Emission flow speciation](flow_speciation.csv): HAP speciation profiles for marine engines.
Source [EPA 2022, Table D.1](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)

- [Engine load factor](engine_load_factor.csv): Low load adjustment factors (<2%).
Source: [EPA 2022, Table 3.10](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)

- Hotel hours: For [foreign ports](hotel_hours.csv), averaged days by region and converted to hours.
For [US ports](hotel_hours_us.csv), hours are sourced from BTS. Source: [Statista 2022](https://www.statista.com/statistics/1101596/port-turnaround-times-by-country/#:~:text=Median%20time%20spent%20in%20port%20by%20container%20ships%20worldwide%20by%20segment%202021&text=In%202021%2C%20container%20ships%20spent,port%20during%20a%20port%20call.), [BTS 2022a](https://data.bts.gov/stories/s/Container-Vessel-Dwell-Times/pbag-pyes), and [BTS 2022b](https://data.bts.gov/stories/s/Tanker-Vessel-Dwell-Times/ari2-ub6a)

- [Transit speed ratios](transit_speed_ratios.csv): Used to calculate typical speeds from max speed.
Source: [EPA 2022, Table 3.12](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P1014J1S.pdf)
