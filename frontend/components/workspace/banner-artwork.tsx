'use client';

import './banner-artwork.css';

/** Each scene is decorative context, not a live trace or reported progress. */
export const artworkScenes = {
  incidents:'scan', approvals:'authorize', knowledge:'pages', operations:'records', memory:'archive', mcp:'bridge',
  automations:'branch', jobs:'queue', quality:'prism', system:'infrastructure', developer:'circuit', settings:'permissions',
  'knowledge-search':'search', 'knowledge-answer':'answer', 'operations-orders':'parcel', 'operations-payments':'ledger',
  'mcp-tools':'tools', 'mcp-access':'keys', 'mcp-activity':'events', 'jobs-recovery':'recovery',
  'approvals-review':'stamp', 'incidents-intake':'intake', 'knowledge-document':'extract',
} as const;
export type ArtworkKey = keyof typeof artworkScenes;
type Scene = typeof artworkScenes[ArtworkKey];

const contextArtwork: Readonly<Record<string,ArtworkKey>> = {
  'knowledge:Search':'knowledge-search', 'knowledge:Ask Knowledge':'knowledge-answer', 'knowledge:document':'knowledge-document',
  'operations:Orders':'operations-orders', 'operations:Payments':'operations-payments',
  'mcp:Tool catalog':'mcp-tools', 'mcp:Access':'mcp-access', 'mcp:Activity':'mcp-activity',
  'jobs:Approval recovery':'jobs-recovery', 'approvals:review':'approvals-review', 'incidents:intake':'incidents-intake',
};
export function artworkForContext(kind:ArtworkKey,variant?:string):ArtworkKey {
  return contextArtwork[`${kind}:${variant??''}`]??kind;
}

export function BannerSurround({scene}:{scene:Scene}) {
  return <svg className={`banner-atmosphere atmosphere-${scene}`} viewBox="0 0 420 300" fill="none" aria-hidden="true">
    {(scene==='scan'||scene==='search')&&<><path d="M93 98V64H130M290 64H327V98M93 202V236H130M290 236H327V202"/><g className="scene-animated scan-reticle"><rect x="80" y="90" width="260" height="120" rx="18" strokeDasharray="2 10"/></g><g className="scene-animated scan-band"><path d="M62 115H358"/><path d="M82 120H338" opacity=".25"/></g></>}
    {scene==='authorize'&&<><path d="M135 56L210 28L285 56V178C285 223 248 252 210 270C172 252 135 223 135 178Z" opacity=".3"/><g className="scene-animated authorization-boundary"><path d="M109 73L210 36L311 73V175C311 227 258 261 210 282C162 261 109 227 109 175Z" strokeDasharray="3 12"/></g><g className="scene-animated authorization-seal"><circle cx="210" cy="150" r="108" strokeDasharray="1 16"/></g></>}
    {scene==='stamp'&&<><g className="scene-animated stamp-frame"><path d="M102 56H279L319 96V247H102ZM279 56V96H319" strokeDasharray="4 10"/><path d="M72 91V66H90M328 225H351V202"/></g><circle className="scene-animated stamp-ring" cx="260" cy="200" r="66" strokeDasharray="2 10"/></>}
    {(scene==='pages'||scene==='extract')&&<>{[0,1,2].map(i=><g key={i} className={`scene-animated passage-frame passage-${i}`}><path d={`M${57+i*19} ${78+i*16}H${108+i*19}V${204-i*6}H${57+i*19}Z`}/><path d={`M${312-i*15} ${88+i*19}H${363-i*15}V${205+i*9}H${312-i*15}Z`}/></g>)}</>}
    {(scene==='records'||scene==='parcel'||scene==='ledger')&&<><path d="M45 95H110L160 145H256L306 204H375M45 221H115L164 170H271L323 88H375"/><g className="scene-animated record-packet"><circle cx="45" cy="95" r="3" fill="currentColor"/></g><g className="scene-animated record-packet packet-return"><circle cx="45" cy="221" r="2" fill="currentColor"/></g><path d="M86 74V56H111M310 239H335V221" opacity=".5"/></>}
    {scene==='archive'&&<>{[0,1,2].map(i=><g key={i} className={`scene-animated archive-frame archive-${i}`}><path d={`M${82+i*22} ${82+i*12}L${274+i*14} ${54+i*18}V${203+i*17}L${82+i*22} ${237+i*8}Z`}/></g>)}</>}
    {scene==='bridge'&&<><path d="M84 90H62V210H84M336 90H358V210H336M64 120H356M64 150H356M64 180H356"/><g className="scene-animated bridge-packet"><rect x="65" y="117" width="16" height="5" rx="2" fill="currentColor"/></g><g className="scene-animated bridge-packet bridge-return"><rect x="338" y="177" width="16" height="5" rx="2" fill="currentColor"/></g></>}
    {scene==='branch'&&<><path d="M43 150H148L245 65H373M148 150H373M148 150L245 235H373"/><g className="scene-animated branch-packet branch-top"><circle cx="43" cy="150" r="3" fill="currentColor"/></g><g className="scene-animated branch-packet branch-bottom"><circle cx="43" cy="150" r="2" fill="currentColor"/></g><circle cx="148" cy="150" r="5"/></>}
    {scene==='queue'&&<>{[0,1,2].map(i=><g key={i}><path d={`M50 ${92+i*58}H370`}/><g className={`scene-animated queue-packet queue-${i}`}><rect x="52" y={88+i*58} width="22" height="7" rx="3" fill="currentColor"/></g><path d={`M53 ${79+i*58}V${105+i*58}M367 ${79+i*58}V${105+i*58}`}/></g>)}</>}
    {scene==='prism'&&<><path d="M210 26L366 150L210 274L54 150Z"/><path d="M210 47L341 150L210 253L79 150Z" strokeDasharray="2 9"/><g className="scene-animated prism-sweep"><path d="M210 150L210 34L269 63Z" fill="currentColor" opacity=".08"/><path d="M210 34V73"/></g></>}
    {scene==='infrastructure'&&<><path d="M77 218L210 44L343 218Z"/><path d="M77 218H343M210 44V259" strokeDasharray="3 9"/>{[[77,218],[210,44],[343,218]].map(([x,y],i)=><circle key={i} className={`scene-animated infrastructure-ping ping-${i}`} cx={x} cy={y} r="12"/>)}</>}
    {scene==='circuit'&&<><path d="M34 70H111V114H154M34 230H111V184H154M386 70H309V114H266M386 230H309V184H266M78 45V65M342 255V235"/>{[[111,70],[111,230],[309,70],[309,230]].map(([x,y],i)=><g key={i} className={`scene-animated circuit-signal signal-${i}`}><circle cx={x} cy={y} r="4" fill="currentColor"/></g>)}</>}
    {scene==='permissions'&&<><path d="M210 34L319 91V209L210 266L101 209V91Z"/><g className="scene-animated permission-boundary"><path d="M210 16L337 82V218L210 284L83 218V82Z" strokeDasharray="2 12"/></g><path d="M42 150H83M337 150H378M210 16V0M210 300V284"/></>}
    {scene==='answer'&&<><path d="M46 99H107Q125 99 125 117V134M46 212H107Q125 212 125 194V180M374 155H307"/>{[0,1,2].map(i=><g key={i} className={`scene-animated answer-stream answer-${i}`}><path d={`M${52+i*7} ${93+i*9}H${104+i*7}`}/></g>)}<path className="scene-animated answer-bloom" d="M317 128L337 150L317 172"/></>}
    {scene==='tools'&&<>{[[68,89],[332,89],[210,252]].map(([x,y],i)=><g key={i} className={`scene-animated tool-slot slot-${i}`}><rect x={x-17} y={y-17} width="34" height="34" rx="8"/><path d={`M${x-7} ${y}H${x+7}M${x} ${y-7}V${y+7}`}/></g>)}<path d="M85 89H121M299 89H315M210 234V219"/></>}
    {scene==='keys'&&<>{[0,1,2].map(i=><g key={i} className={`scene-animated key-scope key-${i}`}><path d={`M${73+i*20} ${73+i*22}V${228-i*17}H${111+i*15}M${347-i*20} ${73+i*22}V${228-i*17}H${309-i*15}`}/></g>)}</>}
    {scene==='events'&&<><g className="scene-animated event-wave"><path d="M24 159H71L93 121L117 186L145 99L173 212L203 73L234 226L267 106L295 181L322 130L345 159H396"/></g>{[[93,121],[173,212],[267,106],[345,159]].map(([x,y],i)=><circle key={i} className={`scene-animated circuit-signal signal-${i}`} cx={x} cy={y} r="3" fill="currentColor"/>)}</>}
    {scene==='recovery'&&<><g className="scene-animated recovery-loop"><path d="M304 83A113 113 0 1 0 329 178M304 83H331V56"/></g><path d="M78 240H132M288 240H342M185 56H235" strokeDasharray="3 9"/><g className="scene-animated recovery-checkpoint"><rect x="188" y="239" width="44" height="11" rx="5"/></g></>}
    {scene==='intake'&&<><path d="M84 82V54H123M297 54H336V82M84 218V246H123M297 246H336V218"/>{[0,1,2].map(i=><g key={i} className={`scene-animated intake-line intake-${i}`}><path d={`M42 ${111+i*37}H105M315 ${111+i*37}H378`}/></g>)}</>}
  </svg>;
}
