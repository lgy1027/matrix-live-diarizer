import { apiClient, call } from './client'

export interface ProcessingManifest {
  version?: number|string
  strategy?: string
  asr?: { engine?: string; model?: string; timestamp_granularity?: string; language?: string }
  diarization?: { provider?: string; status?: string; alignment?: string }
  speaker_identity?: { engine?: string; model_id?: string }
  generated_at?: string
}
export interface Meeting { id:string; title:string; source:'live'|'upload'; status:string; transcript_state?:'draft'|'refined'; duration_sec:number|null; processing_mode:string; processing_manifest?:ProcessingManifest|null; error_message?:string; diarization_status?:'not_requested'|'pending'|'completed'|'unavailable'; diarization_error?:string; created_at:string; updated_at:string }
export interface Job { id:string; meeting_id:string; meeting_title:string; status:string; stage:string; progress:number; error_message?:string; cancel_requested:boolean; created_at:string }
export interface VoiceSample { id:string; person_id:string; duration_sec:number; effective_speech_sec:number; quality_score?:number|null; embedding_dim?:number|null; model_name?:string|null; model_id?:string|null; embedding_status:'ready'|'stale'; created_at:string }
export interface VoiceSampleUploadResult { id:string; duration_sec:number; quality_score:number; effective_speech_sec:number; model_id:string; embedding_status:string; auto_match_eligible:boolean }
export interface Person { id:string; name:string; notes?:string; sample_count:number; total_sample_duration:number; meeting_count?:number }
export interface PersonDetail extends Person { samples:VoiceSample[] }
export type IdentityStatus = 'anonymous'|'suggested'|'auto_matched'|'confirmed'
export interface Speaker { id:string; label:string; person_id?:string; person_name?:string; confidence?:number; manually_confirmed:number; identity_status:IdentityStatus }
export interface Segment { id:number; text:string; start_time:number; end_time:number; speaker_label?:string; person_name?:string; meeting_speaker_id?:string; manually_confirmed?:number; confidence?:number; manually_edited?:number; identity_status?:IdentityStatus }
export interface MeetingNote {id:number;note_type:'summary'|'minutes'|'actions';content:string;source:string}
export interface MeetingDetail { meeting:Meeting; speakers:Speaker[]; segments:Segment[];notes:MeetingNote[];processing_job?:Partial<Job>|null }

export const listMeetings = (params:Record<string, unknown> = {}) => call<{total:number;items:Meeting[]}>({url:'/v1/meetings', params})
export const getMeeting = (id:string) => call<MeetingDetail>({url:`/v1/meetings/${id}`})
export const updateMeeting = (id:string,title:string) => call<Meeting>({method:'PATCH',url:`/v1/meetings/${id}`,data:{title}})
export const deleteMeeting = (id:string) => call({method:'DELETE',url:`/v1/meetings/${id}`})
export const reprocessMeeting = (id:string) => call<{meeting_id:string;job_id:string;status:string}>({method:'POST',url:`/v1/meetings/${id}/reprocess`})
export const searchMeetings = (q:string) => call<{hits:Array<{segment_id:number;meeting_id:string;meeting_title:string;text:string;start_time:number;jump_url:string}>}>({url:'/v1/meetings/search',params:{q}})
export const listJobs = () => call<{items:Job[]}>({url:'/v1/jobs'})
export const cancelJob = (id:string) => call({method:'POST',url:`/v1/jobs/${id}/cancel`})
export const retryJob = (id:string) => call({method:'POST',url:`/v1/jobs/${id}/retry`})
export const listPeople = () => call<{items:Person[]}>({url:'/v1/people'})
export const getPerson = (id:string) => call<PersonDetail>({url:`/v1/people/${id}`})
export const createPerson = (name:string, notes='') => call<Person>({method:'POST',url:'/v1/people',data:{name,notes:notes||null}})
export const deletePerson = (id:string) => call({method:'DELETE',url:`/v1/people/${id}`})
export const deleteVoiceSample = (personId:string,sampleId:string) => call({method:'DELETE',url:`/v1/people/${personId}/samples/${sampleId}`})
export async function getVoiceSampleAudioUrl(personId:string,sampleId:string) { const r=await apiClient.get(`/v1/people/${personId}/samples/${sampleId}/audio`,{responseType:'blob',timeout:0});return URL.createObjectURL(r.data) }
export const confirmSpeaker = (meetingId:string,speakerId:string,personId:string|null) => call({method:'PATCH',url:`/v1/meetings/${meetingId}/speakers/${speakerId}/person`,data:{person_id:personId}})
export const updateSegmentText = (meetingId:string,segmentId:number,text:string) => call({method:'PATCH',url:`/v1/meetings/${meetingId}/segments/${segmentId}`,data:{text}})
export const assignSegmentSpeaker = (meetingId:string,segmentIds:number[],speakerId:string|null) => call<{updated:number}>({method:'PATCH',url:`/v1/meetings/${meetingId}/segments/speaker`,data:{segment_ids:segmentIds,meeting_speaker_id:speakerId}})
export const generateMeetingNote = (meetingId:string,type:'summary'|'minutes'|'actions') => call<MeetingNote>({method:'POST',url:`/v1/meetings/${meetingId}/notes/${type}`})
export const saveMeetingNote = (meetingId:string,type:string,content:string) => call<MeetingNote>({method:'PUT',url:`/v1/meetings/${meetingId}/notes/${type}`,data:{content}})
export async function getMeetingAudioUrl(id:string) { const r=await apiClient.get(`/v1/meetings/${id}/audio`,{responseType:'blob',timeout:0});return URL.createObjectURL(r.data) }
export async function uploadMeeting(file:File, mode:'quick'|'meeting', onProgress?:(n:number)=>void) {
  const data = new FormData(); data.append('file',file,file.name||'upload.wav')
  const response = await apiClient.post(`/v1/meetings/upload?mode=${mode}`, data, {timeout:0,onUploadProgress:e=>onProgress?.(e.total ? Math.round(e.loaded/e.total*100):0)})
  return response.data as {meeting_id:string;job_id:string}
}
export async function uploadVoiceSample(personId:string,file:File):Promise<VoiceSampleUploadResult> { const data=new FormData();data.append('file',file,file.name||'voice-sample.wav');return (await apiClient.post(`/v1/people/${personId}/samples`,data,{timeout:0})).data }
export async function downloadMeeting(id:string, format:'markdown'|'srt'|'vtt'|'json') { const r=await apiClient.get(`/v1/meetings/${id}/export`,{params:{format},responseType:'blob',timeout:0});const url=URL.createObjectURL(r.data);const a=document.createElement('a');a.href=url;a.download=`meeting.${format==='markdown'?'md':format}`;document.body.appendChild(a);a.click();a.remove();window.setTimeout(()=>URL.revokeObjectURL(url),10000) }
