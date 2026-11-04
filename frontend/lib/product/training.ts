import {z} from 'zod';
export const trainingCapabilitiesSchema=z.object({
 enabled:z.boolean(),qlora_enabled:z.boolean(),model_id:z.string(),model_revision:z.string(),
 worker_online:z.boolean(),worker_last_seen_at:z.string().nullable(),worker_device:z.enum(['cpu','cuda']).nullable(),
 max_dataset_bytes:z.number().int().positive(),max_examples:z.number().int().positive(),max_steps:z.number().int().positive(),max_runtime_seconds:z.number().int().positive(),
});
export const trainingProgressSchema=z.object({stage:z.enum(['preparing','loading','training','validating','evaluating','packaging']),completed_steps:z.number().int().nonnegative(),epoch:z.number().int().nonnegative(),validation_loss:z.number().finite().nonnegative().nullable().optional()});
const metrics=z.object({total:z.number().int().positive(),category_accuracy:z.number().min(0).max(1),priority_accuracy:z.number().min(0).max(1),joint_accuracy:z.number().min(0).max(1),invalid_outputs:z.number().int().nonnegative(),infrastructure_errors:z.number().int().nonnegative(),critical_misses:z.number().int().nonnegative(),high_risk_downgrades:z.number().int().nonnegative(),latency_p95_seconds:z.number().finite().nonnegative().nullable()});
export const trainingRunSchema=z.object({id:z.string().uuid(),name:z.string(),status:z.enum(['queued','running','cancel_requested','cancelled','succeeded','failed']),method:z.enum(['lora','qlora']),rank:z.number().int(),epochs:z.number().int(),max_steps:z.number().int(),max_tokens:z.number().int(),model_id:z.string(),model_revision:z.string(),dataset_source:z.enum(['synthetic','reviewed']),example_count:z.number().int(),split_counts:z.record(z.number().int()),progress:trainingProgressSchema,metrics:metrics.nullable(),error_code:z.string().nullable(),artifact_sha256:z.string().nullable(),artifact_bytes:z.number().int().nullable(),created_at:z.string(),started_at:z.string().nullable(),completed_at:z.string().nullable(),production_approved:z.literal(false)});
export const trainingRunsSchema=z.object({items:z.array(trainingRunSchema)});
export const trainingDownloadSchema=z.object({url:z.string().url().refine(value=>new URL(value).protocol==='https:','Expected a secure download URL'),sha256:z.string().regex(/^[a-f0-9]{64}$/),bytes:z.number().int().positive(),expires_in:z.number().int().positive()});
export type TrainingRun=z.infer<typeof trainingRunSchema>;
export function activeTraining(status:string):boolean{return ['queued','running','cancel_requested'].includes(status);}
export function checkTrainingDataset(text:string,limit:number):{examples:number;groups:number}{
 if(new TextEncoder().encode(text).byteLength>limit)throw new Error(`The dataset must be at most ${limit.toLocaleString()} UTF-8 bytes.`);
 const lines=text.split(/\r?\n/).filter(line=>line.trim());if(!lines.length||lines.length>1000)throw new Error('Choose between 1 and 1,000 JSONL examples.');
 const groups=new Set<string>();const categories=['payment','account','access','data','integration','system','security','other'];const priorities=['low','medium','high','critical'];
 lines.forEach((line,index)=>{let row:unknown;try{row=JSON.parse(line);}catch{throw new Error(`Line ${index+1} is not valid JSON.`);}const parsed=z.object({title:z.string().trim().min(1).max(200),description:z.string().trim().min(1).max(8192),category:z.string().refine(v=>categories.includes(v)),priority:z.string().refine(v=>priorities.includes(v)),group_id:z.string().trim().min(1).max(100)}).strict().safeParse(row);if(!parsed.success)throw new Error(`Line ${index+1}: check title, description, category, priority and group_id.`);groups.add(parsed.data.group_id);});
 if(groups.size<3)throw new Error('Use at least three independent group IDs for train, validation and test splits.');return {examples:lines.length,groups:groups.size};
}
/** Idempotency IDs also work on local HTTP previews where randomUUID is absent. */
export function newTrainingRequestId(source:Pick<Crypto,'getRandomValues'> & {randomUUID?:()=>string}=crypto):string{
 if(typeof source.randomUUID==='function')return source.randomUUID();
 const bytes=source.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
 const hex=Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
 return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
