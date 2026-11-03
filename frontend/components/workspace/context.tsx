'use client';
import {createContext,useContext} from 'react';
import type {Me,Role,Workspace} from '@/lib/product/contracts';
export type SessionContext={me:Me;organizationId:string;role:Role;workspace:Workspace|null;notify:(message:string)=>void};
export const Session=createContext<SessionContext|null>(null);
export function useSession(){const value=useContext(Session);if(!value)throw new Error('Workspace context is unavailable');return value;}
