import { z } from 'zod';
export const membershipSchema = z.object({ organization_id: z.string().uuid(), role: z.enum(['owner','admin','operator','reviewer','viewer']) });
export const meSchema = z.object({ user: z.object({ id:z.string(),email:z.string(),full_name:z.string(),is_active:z.boolean() }), memberships:z.array(membershipSchema) });
export type Me = z.infer<typeof meSchema>;
export type Role = z.infer<typeof membershipSchema>['role'];
export const incidentSchema = z.object({id:z.string(),organization_id:z.string(),title:z.string(),description:z.string(),status:z.string(),category:z.string().nullable(),priority:z.string().nullable(),subject_customer_id:z.string().nullable(),created_at:z.string(),updated_at:z.string(),resolution_reason:z.string().nullable().optional(),resolved_at:z.string().nullable().optional()});
export type Incident = z.infer<typeof incidentSchema>;
export const jobSchema = z.object({id:z.string(),organization_id:z.string(),job_type:z.string(),status:z.string(),resource_id:z.string().nullable(),progress_percent:z.number(),error_message:z.string().nullable(),created_at:z.string(),started_at:z.string().nullable(),completed_at:z.string().nullable(),updated_at:z.string()});
export type Job = z.infer<typeof jobSchema>;
export const evidenceSchema = z.object({chunk_id:z.string(),document_id:z.string(),chunk_index:z.number(),page_number:z.number(),text:z.string(),source_filename:z.string(),vector_score:z.number(),reranker_score:z.number()});
export type Evidence = z.infer<typeof evidenceSchema>;
const memorySchema = z.object({memory_id:z.string(),incident_id:z.string(),category:z.string(),summary:z.string(),resolution:z.string(),vector_score:z.number()});
export const investigationSchema = z.object({incident_id:z.string(),workflow_thread_id:z.string(),status:z.string(),category:z.string(),priority:z.string(),classification_confidence:z.number(),approval_required:z.boolean(),approval_request_id:z.string().nullable(),needs_more_information:z.boolean(),clarification_question:z.string().nullable(),analysis:z.string().nullable(),recommended_action:z.string().nullable(),retrieval_query:z.string(),evidence:z.array(evidenceSchema),similar_memories:z.array(memorySchema),tool_results:z.array(z.object({call_id:z.string(),tool_name:z.string(),arguments:z.record(z.unknown()),success:z.boolean(),content:z.string()})),memory_id:z.string().nullable(),memory_indexed:z.boolean()});
export type Investigation = z.infer<typeof investigationSchema>;
export const approvalSchema=z.object({id:z.string(),incident_id:z.string(),organization_id:z.string(),workflow_thread_id:z.string(),action_type:z.string(),action_payload:z.record(z.unknown()),reason:z.string(),status:z.string(),decided_by_user_id:z.string().nullable(),decision_comment:z.string().nullable(),decided_at:z.string().nullable(),executed_at:z.string().nullable(),superseded_by_approval_id:z.string().nullable().optional(),supersession_reason:z.string().nullable().optional(),created_at:z.string(),updated_at:z.string()});
export type Approval=z.infer<typeof approvalSchema>;
export const documentSchema=z.object({id:z.string(),organization_id:z.string(),original_filename:z.string(),mime_type:z.string(),size_bytes:z.number(),status:z.string(),created_at:z.string(),failure_reason:z.string().nullable()});
export type DocumentRecord=z.infer<typeof documentSchema>;
export const rowSchema=z.record(z.unknown());
export type Row=z.infer<typeof rowSchema>;
export const pageSchema=z.object({items:z.array(rowSchema),total:z.number(),limit:z.number(),offset:z.number()});
export type PageResult=z.infer<typeof pageSchema>;
export const workspaceSchema=z.object({organization_id:z.string(),name:z.string(),slug:z.string(),role:z.string(),environment:z.string(),integrations:z.array(z.object({name:z.string(),role:z.string(),configured:z.boolean(),model:z.string().nullable().optional()})),approval_execution_enabled:z.boolean(),mcp_resource_url:z.string()});
export type Workspace=z.infer<typeof workspaceSchema>;
export const latestSchema=z.object({job:jobSchema.nullable(),approval:approvalSchema.nullable()});
export const overviewSchema=z.object({incidents:z.number(),open_incidents:z.number(),awaiting_approval:z.number(),pending_approvals:z.number(),failed_jobs:z.number(),pending_automation:z.number(),documents:z.number(),memories:z.number()});
export const readinessSchema=z.object({status:z.string(),dependencies:z.record(z.object({status:z.string(),duration_ms:z.number()}))});
export const searchSchema=z.object({query:z.string(),results:z.array(evidenceSchema)});
export const answerSchema=z.object({question:z.string(),answer:z.string(),citations:z.array(z.object({source_number:z.number(),document_id:z.string(),chunk_id:z.string(),source_filename:z.string(),page_number:z.number()}))});
export function can(role:Role|undefined, action:'create'|'investigate'|'review'|'document'|'admin'):boolean {
 if(!role)return false;
 if(action==='admin')return role==='owner'||role==='admin';
 if(action==='review')return ['owner','admin','reviewer'].includes(role);
 if(action==='investigate')return role!=='viewer';
 return ['owner','admin','operator'].includes(role);
}
export function stringValue(value:unknown):string { if(value===null||value===undefined)return '—'; if(typeof value==='object')return JSON.stringify(value);return String(value); }
export function dateValue(value:unknown):string {if(typeof value!=='string')return '—';const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString();}
