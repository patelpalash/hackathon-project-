export interface NetNode { id: string; name: string; type: "hub" | "branch"; lat: number; lon: number; relation?: string; source: string; }
export interface Edge { id: string; from: string; to: string; km: number; base_drive_minutes: number; cost_eur: number; cost_special_eur: number; capacity_ldm: number; relation: string; source: string; }
export interface NetworkDoc { hub_id: string; nodes: NetNode[]; edges: Edge[]; }

export interface TransferStat { samples: number; spillover_rate: number; avg_utilisation: number; avg_transfer_minutes: number; median_transfer_minutes: number; range_minutes: number[]; source: string; }
export interface RelationHistory { samples: number; avg_utilisation: number; spillover_rate: number; special_trip_rate: number; avg_line_trailers: number; avg_daily_cost_eur: number; avg_daily_fuel_l: number; avg_volume_ldm: number; reliability_pct: number; source: string; }
export interface OperationalDelay { minutes: number; reason: string; note?: string; status: string; at: string; }
export interface Hub extends NetNode { transfer: TransferStat | Record<string, never>; history: RelationHistory | Record<string, never>; operational_delay: OperationalDelay | null; expected_transfer_minutes: number; }

export interface JourneyStep { type: "handling" | "drive" | "legal_wait" | "hub_delay" | "weekend_hold" | "weather"; location: string; location_name: string; start: string; end: string; minutes: number; detail: string; source: string; }
export interface Components { transport: number; transfer: number; hub_delay: number; traffic: number; legal_wait: number; weekend_hold?: number; weather?: number; }
export interface OptCost { transport_eur: number; fuel_l: number; fuel_eur: number; distance_km: number; cost_per_kg: number | null; }
export interface OptRisk { level: string; score: number; reasons: string[]; exposure_eur: number; deadline_ok: boolean; }
export interface OptHistory { avg_cost_eur: number; avg_fuel_l: number; reliability_pct: number; samples: number; }
export interface LiveWeather { id:string; lat:number; lon:number; status:string; source:string; name?:string; condition?:string; temperature_c?:number; rain_mm?:number; wind_kmh?:number; visibility_m?:number; level?:string; delay_minutes?:number; valid_at:string; fetched_at?:string; message?:string; }
export interface Incident { id:string; geometry:{type:string;coordinates: number[] | number[][]}; description:string; delay_minutes:number; source:string; }
export interface MapConditions { weather:LiveWeather[]; incidents:{status:string;items:Incident[];fetched_at?:string}; traffic_configured:boolean; at:string; fetched_at:string; }
export interface TruckProfile { height_m:number; width_m:number; length_m:number; gross_weight_kg:number; }
export interface RouteOption {
  badges?:string[]; optimization?:string; live_weather?:LiveWeather[]; traffic_status?:string;
  traffic_sections?:{geometry:number[][];delay_minutes:number;description:string}[];
  comparison?:{baseline:string;money_saved_eur:number;minutes_saved:number;fuel_saved_l:number};
  historical_comparison?:{scope:string;matched:boolean;relations:string[];samples:number;normalized_cost_eur:number|null;cost_difference_eur:number|null;reliability_pct:number|null;note:string};
  revision?: number; weather_alerts?: WeatherRecord[];
  intermediate_hub?: { hub: string; name: string; reason: string; distance_to_destination_km: number; route_deviation_km: number } | null;
  recommendation_note?: string;
  origin: string; destination: string; path: string[]; depart_at: string; eta: string; total_minutes: number;
  components: Components; steps: JourneyStep[]; data_sources: Record<string, string>; label: string; kind: string;
  cost: OptCost; risk: OptRisk; ldm: number; historical: OptHistory | null; geometry?: number[][] | null;
}
export interface Savings { money_eur: number; fuel_l: number; time_min: number; note: string; }
export interface WeatherObs { node: string; name?: string; observed?: boolean; temp_c?: number; wind_kmh?: number; status: string; error?: string; }
export interface Provider { key: string; name: string; status: string; configured: boolean; kind: string; last_success: string | null; last_attempt: string | null; data_timestamp: string | null; error: string | null; }
export interface RouteResp { revision?: number; options: RouteOption[]; recommended: number; savings: Savings | null; weather: WeatherObs[]; providers: Provider[]; evaluated_at: string; }

export interface Shipment {
  id: string; origin: string; destination: string; current_location: string; route: string[]; next_hub: string | null;
  status: string; planned_departure: string; scheduled_departure: string | null; current_eta: string; required_delivery: string | null;
  distance_km: number; weight_kg: number; container: string | null; value_eur: number; est_cost_eur: number; est_fuel_l: number;
  cost_per_kg: number | null; risk_level: string; customer_segment: string | null; alert: string | null; delay_minutes: number; created_at: string;
  options?: RouteOption[];
}
export interface Holiday { date: string; name: string; region: string; country: string; transport_impact: string; }
export interface AuditEvent { at: string; type: string; detail: string; source: string; }
export interface RelationStat extends RelationHistory { relation: string; destination: string; km: number; cost_line_eur: number; cost_special_eur: number; }
export interface Disruption { from: string; to: string; type: string; description: string; volume_effect: number; recovery_next_day: number; source: string; }
export interface HighValue { id: string; value_eur: number; origin: string; destination: string; current_location: string; route: string[]; required_delivery: string | null; current_eta: string; risk_level: string; exposure_eur: number; reasons: string[]; recommended_action: string; }
export interface Dashboard { counts: Record<string, number>; total: number; at_risk: number; high_value: number; active_hub_delays: number; next_holiday: Holiday | null; estimated_savings_eur: number; providers: Provider[]; generated_at: string; }
export interface SavingsResp { total: { money_eur: number; fuel_l: number; time_min: number; optimized: number }; avg_per_shipment_eur: number; per_shipment: { id: string; container: string | null; money_eur: number; fuel_l: number; time_min: number }[]; note: string; source: string; }

export interface WeatherInput { node: string; start: string; end: string; temperature_c: number; condition: string; rain_mm: number; snow_cm: number; visibility_m: number; wind_kmh: number; severity: string; }
export interface WeatherRecord extends WeatherInput { id: string; alert: boolean; level: string; delay_minutes: number; message: string; action: string; source: string; }
export interface ScenarioEvent { id: string; kind: string; node?: string; origin?: string; destination?: string; start: string; end: string; minutes: number; reason: string; }
export interface Decision { id: string; shipment_id: string; action: string; reason: string; updated_at: string; path: string[]; eta: string; }
export interface Operations { revision: number; weather: WeatherRecord[]; events: ScenarioEvent[]; decisions: Decision[]; }
