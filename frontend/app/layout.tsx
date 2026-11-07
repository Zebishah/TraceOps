import type { Metadata } from 'next';
import './globals.css';
export const metadata:Metadata={title:{default:'IncidentIQ — Incident intelligence',template:'%s · IncidentIQ'},description:'Investigate operational incidents with evidence, human approval, and reliable automation.'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><head><link rel="stylesheet" href="/brand/style.css"/><link rel="stylesheet" href="/brand/redesign.css"/><link rel="stylesheet" href="/brand/refinement.css"/><link rel="stylesheet" href="/brand/polish.css"/></head><body>{children}</body></html>;}
