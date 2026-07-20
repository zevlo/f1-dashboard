// Telemetry domain types — mirror the DynamoDB schemas enforced by the
// transformer Lambda. Numbers come back as numbers (api-replay Lambda coerces
// Decimals); strings stay strings.

export type SessionMode = 'live' | 'historical'

export type SessionStatus = 'active' | 'completed'

export interface Session {
  session_key: string
  session_type: string | null
  session_name: string | null
  circuit_short_name: string | null
  country_name: string | null
  date_start: string | null
  date_end: string | null
  year: number | null
  status: SessionStatus
}

export interface Driver {
  session_key: string
  driver_number: number
  full_name: string | null
  broadcast_name: string | null
  name_acronym: string | null
  team_name: string | null
  team_colour: string | null
  country_code: string | null
  headshot_url: string | null
}

export interface PositionSample {
  session_key: string
  ts_driver: string
  driver_number: number
  position: number
  date: string
}

export interface Lap {
  // PK session_driver is included so we can recover driver_number on the client.
  session_driver: string
  lap_number: number
  date_start: string | null
  lap_duration: number | null
  sector_1: number | null
  sector_2: number | null
  sector_3: number | null
  is_pit_out_lap: boolean | null
  compound: string | null
}

export interface RaceControlEvent {
  session_key: string
  timestamp: string
  category: string | null
  flag: string | null
  message: string | null
  driver_number: number | null
}

export interface CarTelemetry {
  session_driver: string
  date: string
  driver_number: number
  speed: number | null
  throttle: number | null
  brake: boolean | null
  n_gear: number | null
  rpm: number | null
  drs: number | null
}

// Bulk replay payload from GET /sessions/{key}/replay
export interface ReplayPayload {
  session: Session
  drivers: Driver[]
  positions: PositionSample[]
  laps: Lap[]
  race_control: RaceControlEvent[]
  counts: {
    drivers: number
    positions: number
    laps: number
    race_control: number
  }
}

// WebSocket messages — server -> client
export type WsMessage =
  | { type: 'position.update'; data: { driver_number: number; position: number; ts: string } }
  | { type: 'car_data.update'; data: CarTelemetry }
  | { type: 'race_control.event'; data: Omit<RaceControlEvent, 'session_key' | 'timestamp'> & { ts: string } }
  | { type: 'flag.change'; data: { flag: string | null } }
  | { type: 'lap.complete'; data: Omit<Lap, 'session_driver'> & { driver_number: number } }
  | { type: 'agent.token'; messageId: string; token: string }
  | { type: 'agent.done'; messageId: string }
  | { type: 'agent.error'; messageId?: string; error: string }

// WebSocket actions — client -> server
export type WsClientAction =
  | { action: 'agent.ask'; text: string; sessionKey: string | null; driverNumber: number | null }

export type WsConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
