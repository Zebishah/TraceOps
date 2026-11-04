'use client';

import { useId } from 'react';
export type InvestigationStageId = 'report' | 'analysis' | 'evidence' | 'review' | 'outcome';

/** Original vector illustrations. Motion illustrates the workflow, not unreported backend activity. */
export function StageArtwork({ stage }: { stage: InvestigationStageId }) {
  const key = useId().replaceAll(':', '');
  const fill = `url(#${key}-fill)`;
  const line = `url(#${key}-line)`;
  return <svg className={`stage-artwork artwork-${stage}`} viewBox="0 0 360 340" fill="none" aria-hidden="true">
    <defs><linearGradient id={`${key}-fill`} x1="100" y1="60" x2="260" y2="290" gradientUnits="userSpaceOnUse"><stop stopColor="#e6ca92" stopOpacity=".18"/><stop offset="1" stopColor="#b3bd96" stopOpacity=".025"/></linearGradient><linearGradient id={`${key}-line`} x1="90" y1="60" x2="270" y2="290" gradientUnits="userSpaceOnUse"><stop stopColor="#f1d7a3"/><stop offset="1" stopColor="#9aa978" stopOpacity=".5"/></linearGradient><radialGradient id={`${key}-halo`}><stop stopColor="#d4b47e" stopOpacity=".16"/><stop offset="1" stopColor="#d4b47e" stopOpacity="0"/></radialGradient></defs>
    <circle cx="180" cy="164" r="142" fill={`url(#${key}-halo)`}/>
    <g className="art-platform"><ellipse className="art-platform-pulse" cx="180" cy="274" rx="90" ry="22" stroke="#d4b47e" strokeOpacity=".65"/><ellipse cx="180" cy="274" rx="121" ry="31" stroke="#b6a67b" strokeOpacity=".18"/><ellipse cx="180" cy="274" rx="90" ry="22" stroke="#d4b47e" strokeOpacity=".28"/><ellipse cx="180" cy="274" rx="58" ry="13" stroke="#d4b47e" strokeOpacity=".45"/><path d="M40 274H68M292 274H320M180 237V245M180 303V312" stroke="#b6a67b" strokeOpacity=".35"/></g>
    {stage==='report' && <g className="art-levitate">
      <path d="M112 80L241 62L257 236L128 256Z" fill="#172017" stroke="#8f9b70" strokeOpacity=".45"/><path d="M99 68L228 50L244 224L115 244Z" fill={fill} stroke={line}/>
      <path d="M120 101L204 90M124 123L219 110M128 148L211 136M130 160L219 148M134 184L177 178M137 196L213 185" stroke="#d4b47e" strokeOpacity=".38" strokeWidth="2"/>
      <path d="M118 93L146 89" stroke="#edcf94" strokeWidth="3"/><path d="M103 71L229 53L244 224L117 243Z" stroke="#e6c98e" strokeOpacity=".12" strokeWidth="7"/>
      <g className="art-scan"><path d="M88 144L251 121" stroke="#efd19a" strokeWidth="2"/><path d="M88 144L251 121L253 134L90 157Z" fill="#efd19a" fillOpacity=".09"/></g>
      <g className="art-chip-float"><rect x="202" y="196" width="67" height="39" rx="7" fill="#222d1d" stroke="#bca46d" strokeOpacity=".6"/><path d="M215 215L223 223L239 207" stroke="#decb9f" strokeWidth="2"/><path d="M246 212H257M246 219H253" stroke="#9dac7d"/></g>
    </g>}
    {stage==='analysis' && <g>
      <g className="art-chip-base"><path d="M95 222L180 190L267 222L180 255Z" fill="#313b22" stroke={line}/><path d="M95 222V237L180 272L267 237V222M180 255V272" stroke="#b6a16c" strokeOpacity=".55"/><path d="M124 223L180 202L237 223L180 245Z" fill="#d4b47e" fillOpacity=".12" stroke="#d4b47e" strokeOpacity=".5"/>{[0,1,2,3,4].map(n=><g key={n} stroke="#9aa777" strokeOpacity=".6"><path d={`M${111+n*14} ${244+n*5.4}v10M${249-n*14} ${244+n*5.4}v10`}/></g>)}</g>
      <g className="art-brain-float" fill={fill} stroke={line} strokeWidth="1.5"><path d="M178 77C163 56 137 63 133 84C114 79 97 97 102 116C83 126 88 152 105 157C100 179 118 196 138 190C149 207 172 200 178 184V77Z"/><path d="M183 77C198 56 224 63 228 84C247 79 264 97 259 116C278 126 273 152 256 157C261 179 243 196 223 190C212 207 189 200 183 184V77Z"/><path d="M134 85C147 91 144 107 132 111M103 116C126 111 139 129 130 144M107 157C124 151 143 160 139 189M175 109C153 107 147 124 156 139M153 168C166 163 175 170 177 183M227 84C214 91 217 107 229 111M258 116C235 111 222 129 231 144M254 157C237 151 218 160 222 189M186 109C208 107 214 124 205 139M208 168C195 163 186 170 184 183" strokeOpacity=".65"/>
      {[ [133,85],[103,116],[130,144],[139,189],[156,139],[175,109],[228,84],[259,116],[231,144],[222,189],[205,139],[186,109] ].map(([x,y],i)=><circle key={i} className="art-synapse" cx={x} cy={y} r="2.5" fill="#f0d39a" stroke="none" style={{animationDelay:`${i*.21}s`}}/>)}</g><path className="art-data-stream" d="M151 188V214M180 201V226M210 188V214" stroke="#d4b47e" strokeDasharray="3 7" strokeOpacity=".7"/>
    </g>}
    {stage==='evidence' && <g className="art-levitate">
      {[0,1,2].map(n=><g key={n} className={`art-stack-layer stack-layer-${n}`}><path d={`M85 ${130+n*43}L180 ${94+n*43}L275 ${130+n*43}L180 ${166+n*43}Z`} fill="#202a1b" stroke={line}/><path d={`M85 ${130+n*43}V${145+n*43}L180 ${182+n*43}L275 ${145+n*43}V${130+n*43}M180 ${166+n*43}V${182+n*43}`} stroke="#9faa7b" strokeOpacity=".5"/><path d={`M111 ${135+n*43}L153 ${151+n*43}`} stroke="#d4b47e" strokeOpacity=".5"/>{[0,1,2].map(k=><circle key={k} cx={211+k*12} cy={149+n*43-k*4.5} r="2" fill="#d4b47e" fillOpacity=".6"/>)}</g>)}
      <g className="art-evidence-card"><rect x="136" y="50" width="90" height="72" rx="6" fill="#2b3523" stroke="#d4b47e" strokeOpacity=".8"/><path d="M150 67H177M150 79H211M150 90H202M150 101H187" stroke="#d4b47e" strokeOpacity=".55"/><rect x="193" y="60" width="23" height="13" rx="3" fill="#d4b47e" fillOpacity=".15"/><path d="M200 66H208" stroke="#e9d3a8"/></g><path className="art-data-stream" d="M102 100L102 72H124M253 107V68H236" stroke="#b8c397" strokeDasharray="3 7" strokeOpacity=".6"/>
    </g>}
    {stage==='review' && <g className="art-levitate">
      <ellipse className="art-review-ring" cx="180" cy="155" rx="111" ry="96" stroke="#cbb27d" strokeOpacity=".4" strokeDasharray="2 8"/><path d="M180 60L252 90V151C252 201 215 236 180 251C145 236 108 201 108 151V90L180 60Z" fill={fill} stroke={line} strokeWidth="1.5"/><path d="M180 76L237 100V151C237 190 210 220 180 235C150 220 123 190 123 151V100L180 76Z" stroke="#d4b47e" strokeOpacity=".3"/><path className="art-shield-check" d="M149 151L171 173L214 128" stroke="#eed3a1" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/>
      <g className="art-chip-float"><rect x="217" y="197" width="57" height="39" rx="7" fill="#25321f" stroke="#a0b17d"/><circle cx="234" cy="211" r="5" stroke="#c7d4aa"/><path d="M226 224C226 217 242 217 242 224M250 210H263M250 218H259" stroke="#c7d4aa" strokeOpacity=".6"/></g>
    </g>}
    {stage==='outcome' && <g className="art-levitate">
      <path d="M117 80H232V232H117Z" fill="#1d2919" stroke={line}/><path d="M129 68H244V220H129Z" fill={fill} stroke={line}/><path d="M146 96H205M146 116H226M146 137H215M146 158H219M146 180H184" stroke="#cab17a" strokeOpacity=".5" strokeWidth="2"/><circle cx="222" cy="212" r="37" fill="#293722" stroke="#bccb91" strokeWidth="1.5"/><circle cx="222" cy="212" r="29" stroke="#aabc7b" strokeOpacity=".35"/><path d="M206 212L218 224L240 200" stroke="#d2dda9" strokeWidth="3" strokeLinecap="round"/>
      <path className="art-data-stream" d="M92 181H65V226H92M265 103H290V160H271" stroke="#c8b17a" strokeDasharray="3 7" strokeOpacity=".5"/><circle className="art-synapse" cx="65" cy="205" r="4" fill="#d4b47e"/><circle className="art-synapse" cx="290" cy="139" r="3" fill="#c2ce9f"/>
    </g>}
    <g stroke="#a9b98b" strokeOpacity=".4"><path d="M52 112V91H73M285 61H306V82M56 231V250H75M294 222V241H275"/></g>
  </svg>;
}
