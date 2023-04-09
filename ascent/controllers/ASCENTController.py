import glob
import json
import math
import os
import pandas as pd

from settings import settings


class SIMInput:
    @staticmethod
    def get_input(lat_FSS: float, lon_FSS: float, radius: int, simulation_count: int, bs_ue_max_radius: int,
                  bs_ue_min_radius: int, base_station_count: int, base_stations: dict, rain: bool, rain_rate: float):
        return {
            "lat_FSS": lat_FSS,
            "lon_FSS": lon_FSS,
            "radius": radius,
            "simulation_count": simulation_count,
            "bs_ue_max_radius": bs_ue_max_radius,
            "bs_ue_min_radius": bs_ue_min_radius,
            "base_station_count": base_station_count,
            "base_stations": base_stations,
            "rain": rain,
            "rain_rate": rain_rate
        }


class ASCENTController:
    EXCLUSION_ZONE_RADIUS = None
    EXCLUSION_ZONE_RADIUS_STEP = None
    SIMULATION_COUNT = None
    BS_COUNT = None
    BS_UE_RADIUS_MIN = None
    BS_UE_RADIUS_MAX = None
    FSS_COOR = None
    BASE_STATIONS: pd.DataFrame = None

    sim_input = SIMInput()
    settings_file = settings.SIM_SETTINGS_FILE

    def __init__(self):
        self.EXCLUSION_ZONE_RADIUS = settings.EXCLUSION_ZONE_RADIUS
        self.EXCLUSION_ZONE_RADIUS_STEP = settings.EXCLUSION_ZONE_RADIUS_STEP
        self.SIMULATION_COUNT = settings.SIMULATION_COUNT
        self.BS_COUNT = settings.BS_COUNT
        self.BS_UE_RADIUS_MIN = settings.BS_UE_RADIUS[0]
        self.BS_UE_RADIUS_MAX = settings.BS_UE_RADIUS[1]

        self.FSS_COOR = [37.20250, -80.43444]  # Hard-coded

        self.rain = True
        self.rain_rate = 33.0  # FSS location's rain rate in mm/h

        self.BASE_STATIONS = self.generate_BS_list(self.BS_COUNT)

        sim_settings = self.configure_simulator_settings()

    def configure_simulator_settings(self, sim_sett=None):
        if sim_sett is None:
            sim_sett = {}

        self.EXCLUSION_ZONE_RADIUS = sim_sett.get("radius", self.EXCLUSION_ZONE_RADIUS)
        self.SIMULATION_COUNT = sim_sett.get("simulation_count", self.SIMULATION_COUNT)
        self.BS_UE_RADIUS_MAX = sim_sett.get("bs_ue_max_radius", self.BS_UE_RADIUS_MAX)
        self.BS_UE_RADIUS_MIN = sim_sett.get("bs_ue_min_radius", self.BS_UE_RADIUS_MIN)

        if "base_station_count" in sim_sett:
            if sim_sett["base_station_count"] != self.BS_COUNT:
                self.BS_COUNT = sim_sett.get("base_station_count", self.BS_COUNT)
                self.BASE_STATIONS = self.generate_BS_list(self.BS_COUNT)

        data = {
            "radius": self.EXCLUSION_ZONE_RADIUS,
            "simulation_count": self.SIMULATION_COUNT,
            "bs_ue_max_radius": self.BS_UE_RADIUS_MAX,
            "bs_ue_min_radius": self.BS_UE_RADIUS_MIN,
            "base_station_count": self.BS_COUNT,
            "base_stations": self.BASE_STATIONS.to_dict("records")
        }

        with open(self.settings_file, "w+") as outfile:
            json.dump(data, outfile, indent=3, sort_keys=True)

        return data

    def get_simulator_input(self):
        return self.sim_input.get_input(
            self.FSS_COOR[0],
            self.FSS_COOR[1],
            self.EXCLUSION_ZONE_RADIUS,
            self.SIMULATION_COUNT,
            self.BS_UE_RADIUS_MAX,
            self.BS_UE_RADIUS_MIN,
            self.BS_COUNT,
            self.BASE_STATIONS.to_dict("records"),
            self.rain,
            self.rain_rate
        )

    def generate_BS_list(self, bs_count):
        path = "assets"
        all_files = glob.glob(os.path.join(path, "*.csv"))

        all_data = pd.concat((pd.read_csv(
            f, names=["radio", "mcc", "mnc", "lac", "cid", "unit", "longitude",
                      "latitude", "range", "samples", "changeable", "created", "updated", "averageSignal"]
        ) for f in all_files))

        latitude_range = self.EXCLUSION_ZONE_RADIUS / 110574
        longitude_range = self.EXCLUSION_ZONE_RADIUS / (111320 * math.cos(math.radians(latitude_range)))

        data_within_zone = all_data[
            (all_data["radio"] == "GSM")
            & (all_data["longitude"] <= (self.FSS_COOR[1] + longitude_range))
            & (all_data["longitude"] >= (self.FSS_COOR[1] - longitude_range))
            & (all_data["latitude"] <= (self.FSS_COOR[0] + latitude_range))
            & (all_data["latitude"] >= (self.FSS_COOR[0] - latitude_range))
            ]

        selected_bs = data_within_zone.sample(n=bs_count)
        selected_bs["status"] = 1

        return selected_bs
