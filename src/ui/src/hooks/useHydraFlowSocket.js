/**
 * Thin compatibility wrapper — re-exports the reducer for tests
 * and provides useHydraFlowSocket as an alias for useHydraFlow.
 *
 * All state management has moved to HydraFlowContext.
 */
export { reducer, initialState } from '../context/HydraFlowContext'
export { useHydraFlow as useHydraFlowSocket } from '../context/HydraFlowContext'
