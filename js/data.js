// Router that exposes ONE data API and delegates to the active adapter.
// Local by default; switches to cloud after a successful Supabase login.
import * as local from './localAdapter.js';
import * as cloud from './cloudAdapter.js';

let adapter = local;

export function useCloud() { adapter = cloud; }
export function useLocal() { adapter = local; }
export function mode() { return adapter === cloud ? 'cloud' : 'local'; }
export function supportsSharing() { return adapter.supportsSharing; }

// Collections
export const listCollections   = (...a) => adapter.listCollections(...a);
export const createCollection  = (...a) => adapter.createCollection(...a);
export const renameCollection  = (...a) => adapter.renameCollection(...a);
export const deleteCollection  = (...a) => adapter.deleteCollection(...a);
export const importCollection  = (...a) => adapter.importCollection(...a);
// Spots
export const listSpots  = (...a) => adapter.listSpots(...a);
export const addSpot    = (...a) => adapter.addSpot(...a);
export const updateSpot = (...a) => adapter.updateSpot(...a);
export const deleteSpot = (...a) => adapter.deleteSpot(...a);
// Members
export const listMembers  = (...a) => adapter.listMembers(...a);
export const addMember    = (...a) => adapter.addMember(...a);
export const removeMember = (...a) => adapter.removeMember(...a);
// Photos
export const listPhotos  = (...a) => adapter.listPhotos(...a);
export const addPhoto    = (...a) => adapter.addPhoto(...a);
export const deletePhoto = (...a) => adapter.deletePhoto(...a);
// Expenses
export const listExpenses  = (...a) => adapter.listExpenses(...a);
export const addExpense    = (...a) => adapter.addExpense(...a);
export const deleteExpense = (...a) => adapter.deleteExpense(...a);
