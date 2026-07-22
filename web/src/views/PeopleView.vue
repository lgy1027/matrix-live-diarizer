<script setup lang="ts">
import { computed,nextTick,onBeforeUnmount,onMounted,ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  createPerson,
  deletePerson,
  deleteVoiceSample,
  getPerson,
  getVoiceSampleAudioUrl,
  listPeople,
  uploadVoiceSample,
  type Person,
  type PersonDetail,
  type VoiceSample,
} from '../api/product'
import { useDialog } from '../composables/useDialog'
import { startMic, resampleTo16k, type MicHandle } from '../utils/audio'
import { encodeWav } from '../utils/wav'

const {t}=useI18n(),dialog=useDialog()
const items=ref<Person[]>([]),details=ref<Record<string,PersonDetail>>({})
const name=ref(''),busy=ref(''),loading=ref(true),error=ref(''),notice=ref(''),query=ref('')
const expanded=ref(new Set<string>()),detailLoading=ref(''),samplePlayer=ref<HTMLAudioElement|null>(null)
const previewId=ref(''),previewUrl=ref(''),previewPlaying=ref(false),previewLoading=ref('')
// 预览请求版本号:每次发起新预览递增,旧请求返回时发现 token 不匹配则丢弃并 revoke,避免快速连点泄漏 blob URL
let previewToken=0
// 在线录音:每个 person 独立态
const recId=ref(''),recState=ref<'idle'|'recording'|'review'>('idle'),recSecs=ref(0),reviewUrl=ref(''),recordSupported=ref(true)
let recMic:MicHandle|null=null,recTimer:number|undefined=undefined,recChunks:Float32Array[]=[],recBlob:Blob|null=null
const REC_MAX_SECONDS=30

const filtered=computed(()=>{const q=query.value.trim().toLocaleLowerCase();return q?items.value.filter(p=>p.name.toLocaleLowerCase().includes(q)):items.value})

async function load(){loading.value=true;try{items.value=(await listPeople()).items;error.value=''}catch(e){error.value=e instanceof Error?e.message:String(e)}finally{loading.value=false}}
async function loadDetail(personId:string){detailLoading.value=personId;try{details.value={...details.value,[personId]:await getPerson(personId)}}finally{detailLoading.value=''}}
async function toggleDetails(personId:string){const next=new Set(expanded.value);if(next.has(personId)){next.delete(personId)}else{next.add(personId);if(!details.value[personId])await loadDetail(personId)}expanded.value=next}
async function add(){const value=name.value.trim();if(!value)return;busy.value='new';error.value='';notice.value='';try{const person=await createPerson(value);name.value='';notice.value=t('product.people.created',{name:person.name});await load()}catch(e){error.value=e instanceof Error?e.message:String(e)}finally{busy.value=''}}
async function remove(p:Person){const ok=await dialog.showConfirm({title:t('product.people.deleteTitle'),message:t('product.people.deleteConfirm',{name:p.name}),confirmText:t('product.people.delete'),cancelText:t('btn.cancel'),danger:true});if(!ok)return;error.value='';notice.value='';try{stopPreview();await deletePerson(p.id);delete details.value[p.id];await load()}catch(e){error.value=e instanceof Error?e.message:String(e)}}
async function sample(p:Person,e:Event){const input=e.target as HTMLInputElement,f=input.files?.[0];if(!f)return;busy.value=p.id;error.value='';notice.value='';try{const r=await uploadVoiceSample(p.id,f);notice.value=t(r.auto_match_eligible?'product.people.sampleAddedEligible':'product.people.sampleAddedIneligible',{name:p.name});await Promise.all([load(),loadDetail(p.id)]);const next=new Set(expanded.value);next.add(p.id);expanded.value=next}catch(reason){error.value=errText(reason)}finally{busy.value='';input.value=''}}
async function removeSample(p:Person,s:VoiceSample){const ok=await dialog.showConfirm({title:t('product.people.deleteSampleTitle'),message:t('product.people.deleteSampleConfirm',{name:p.name,seconds:s.duration_sec.toFixed(1)}),detail:t('product.people.deleteSampleImpact'),confirmText:t('product.people.deleteSample'),cancelText:t('btn.cancel'),danger:true});if(!ok)return;busy.value=s.id;error.value='';notice.value='';try{if(previewId.value===s.id)stopPreview();await deleteVoiceSample(p.id,s.id);notice.value=t('product.people.sampleDeleted');await Promise.all([load(),loadDetail(p.id)])}catch(reason){error.value=reason instanceof Error?reason.message:String(reason)}finally{busy.value=''}}
async function togglePreview(p:Person,s:VoiceSample){const player=samplePlayer.value;if(!player)return;if(previewId.value===s.id&&previewUrl.value){player.paused?await player.play():player.pause();return}previewLoading.value=s.id;stopPreview();const token=++previewToken;try{const url=await getVoiceSampleAudioUrl(p.id,s.id);if(token!==previewToken){URL.revokeObjectURL(url);return}previewUrl.value=url;previewId.value=s.id;await nextTick();await samplePlayer.value?.play()}catch(reason){if(token===previewToken)error.value=reason instanceof Error?reason.message:String(reason);stopPreview()}finally{previewLoading.value=''}}
function stopPreview(){samplePlayer.value?.pause();if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value='';previewId.value='';previewPlaying.value=false;previewToken++}
// 提取后端 detail(FastAPI 422/400 友好提示),拿不到则退化到 message。
function errText(e:unknown):string{
  const ax=e as {response?:{data?:{detail?:unknown}},message?:string}
  const d=ax?.response?.data?.detail
  if(typeof d==='string'&&d)return d
  return e instanceof Error?e.message:String(e)
}
function qualityLabel(s:VoiceSample){return s.quality_score==null?t('product.people.qualityUnknown'):t('product.people.quality',{score:Math.round(s.quality_score*100)})}
function dateLabel(value:string){const date=new Date(value);return Number.isNaN(date.getTime())?'—':date.toLocaleDateString()}

// 在线录音
function stopRecTimer(){if(recTimer!==undefined){window.clearInterval(recTimer);recTimer=undefined}}
function resetRecState(){if(recMic){recMic.stop();recMic=null}recId.value='';recState.value='idle';recSecs.value=0;if(reviewUrl.value)URL.revokeObjectURL(reviewUrl.value);reviewUrl.value='';recChunks=[];recBlob=null;stopRecTimer()}
async function startRecord(p:Person){error.value='';notice.value='';if(!navigator.mediaDevices?.getUserMedia){recordSupported.value=false;error.value=t('product.people.recordUnsupported');return}resetRecState();recId.value=p.id;try{const mic=await startMic();recMic=mic;recState.value='recording';recSecs.value=0;recChunks=[];const fromRate=mic.actualSampleRate;mic.processor.onaudioprocess=(ev)=>{if(!recMic)return;const in0=ev.inputBuffer.getChannelData(0);recChunks.push(resampleTo16k(in0.slice(),fromRate))};recTimer=window.setInterval(()=>{recSecs.value+=1;if(recSecs.value>=REC_MAX_SECONDS)stopRecord()},1000)}catch(reason){recordSupported.value=false;error.value=t('product.people.recordError',{msg:reason instanceof Error?reason.message:String(reason)});resetRecState()}}
function stopRecord(){
  // 幂等:已在 review/idle 态时(如 30s 自动停后用户又点停)直接返回,不再 reset,
  // 否则 resetRecState 会 revoke 掉刚生成的 reviewUrl、清掉 recBlob,审听界面变空。
  if(!recMic){return}
  const mic=recMic;mic.stop();stopRecTimer();recMic=null
  // 攒好的 Float32 chunks 拼成单段 PCM
  let total=0;for(const c of recChunks)total+=c.length
  const pcm=new Float32Array(total);let off=0
  for(const c of recChunks){pcm.set(c,off);off+=c.length}
  recChunks=[]
  if(total===0){error.value=t('product.people.recordError',{msg:'no audio'});recState.value='idle';return}
  recBlob=encodeWav(pcm,16000);reviewUrl.value=URL.createObjectURL(recBlob);recState.value='review'
}
async function confirmUploadRecord(p:Person){if(!recBlob)return;busy.value=p.id;error.value='';notice.value='';try{const file=new File([recBlob],'voice-sample.wav',{type:'audio/wav'});const r=await uploadVoiceSample(p.id,file);notice.value=t(r.auto_match_eligible?'product.people.sampleAddedEligible':'product.people.sampleAddedIneligible',{name:p.name});resetRecState();await Promise.all([load(),loadDetail(p.id)]);const next=new Set(expanded.value);next.add(p.id);expanded.value=next}catch(reason){error.value=errText(reason)}finally{busy.value=''}}

onMounted(load)
onBeforeUnmount(()=>{stopPreview();resetRecState()})
</script>

<template><section class="product-page"><div class="page-head"><div><div class="eyebrow">{{t('product.people.eyebrow')}}</div><h1>{{t('product.people.title')}}</h1><p>{{t('product.people.lead')}}</p></div></div>
  <section class="people-create"><div><h2>{{t('product.people.createTitle')}}</h2><p>{{t('product.people.createHint')}}</p></div><form class="new-person" @submit.prevent="add"><input v-model="name" maxlength="100" :aria-label="t('product.people.namePlaceholder')" :placeholder="t('product.people.namePlaceholder')"><button type="submit" :disabled="busy==='new'||!name.trim()">{{busy==='new'?t('product.people.creating'):`＋ ${t('product.people.add')}`}}</button></form></section>
  <div class="people-tools"><input v-model="query" class="filter" :aria-label="t('product.people.search')" :placeholder="t('product.people.search')"></div>
  <p v-if="error" class="inline-error" role="alert">{{error}} <button @click="error=''">×</button></p>
  <p v-if="notice" class="inline-notice" role="status">{{notice}} <button @click="notice=''">×</button></p>
  <audio ref="samplePlayer" class="sample-player" :src="previewUrl" @play="previewPlaying=true" @pause="previewPlaying=false" @ended="previewPlaying=false" />
  <div v-if="loading" class="state-card">{{t('common.loading')}}</div><div v-else class="people-grid">
    <article v-for="p in filtered" :key="p.id" :class="{expanded:expanded.has(p.id)}">
      <div class="avatar">{{p.name.slice(0,1).toUpperCase()}}</div>
      <div class="person-copy"><h3>{{p.name}}</h3><p>{{p.sample_count?t('product.people.samples',{count:p.sample_count,seconds:(p.total_sample_duration??0).toFixed(1)}):t('product.people.noSamples')}}</p></div>
      <button class="manage" :aria-expanded="expanded.has(p.id)" @click="toggleDetails(p.id)">{{detailLoading===p.id?t('common.loading'):(expanded.has(p.id)?t('product.people.hideSamples'):t('product.people.manageSamples'))}}</button>
      <div class="sample-actions">
        <label class="sample"><input type="file" accept="audio/*" @change="sample(p,$event)">{{busy===p.id?t('product.people.processing'):t('product.people.addSample')}}</label>
        <button class="sample record" :disabled="recState!=='idle'" @click="startRecord(p)">{{t('product.people.recordSample')}}</button>
      </div>
      <button class="delete" :aria-label="t('product.people.delete')" @click="remove(p)">×</button>
      <section v-if="recId===p.id&&recState!=='idle'" class="recorder-panel">
        <p class="rec-hint">{{t('product.people.recordHint')}}</p>
        <div v-if="recState==='recording'" class="rec-row">
          <span class="rec-timer">{{t('product.people.recording',{s:recSecs})}}</span>
          <button class="rec-stop" @click="stopRecord()">{{t('product.people.stopRecording')}}</button>
        </div>
        <div v-else-if="recState==='review'" class="rec-row">
          <audio class="rec-player" :src="reviewUrl" controls />
          <div class="rec-actions">
            <button @click="startRecord(p)">{{t('product.people.reRecord')}}</button>
            <button class="rec-confirm" :disabled="busy===p.id" @click="confirmUploadRecord(p)">{{busy===p.id?t('product.people.processing'):t('product.people.confirmUpload')}}</button>
          </div>
        </div>
      </section>
      <section v-if="expanded.has(p.id)" class="sample-panel">
        <header><div><h4>{{t('product.people.sampleLibrary')}}</h4><p>{{t('product.people.sampleLibraryHint')}}</p></div><span>{{details[p.id]?.samples.length??0}}</span></header>
        <div v-if="detailLoading===p.id&&!details[p.id]" class="sample-empty">{{t('common.loading')}}</div>
        <div v-else-if="!details[p.id]?.samples.length" class="sample-empty">{{t('product.people.sampleEmpty')}}</div>
        <div v-else class="sample-list">
          <div v-for="(s,index) in details[p.id].samples" :key="s.id" class="sample-row">
            <button class="preview" :class="{playing:previewId===s.id&&previewPlaying}" :disabled="previewLoading===s.id" :aria-label="t(previewId===s.id&&previewPlaying?'product.people.pauseSample':'product.people.playSample')" @click="togglePreview(p,s)"><span>{{previewLoading===s.id?'…':(previewId===s.id&&previewPlaying?'Ⅱ':'▶')}}</span></button>
            <div class="sample-copy"><b>{{t('product.people.sampleName',{number:index+1})}}</b><p>{{t('product.people.sampleMeta',{duration:s.duration_sec.toFixed(1),effective:s.effective_speech_sec.toFixed(1),date:dateLabel(s.created_at)})}}</p><code :title="s.model_id||s.model_name||''">{{s.model_name||s.model_id||t('product.people.modelUnknown')}}</code></div>
            <span class="quality" :class="{good:(s.quality_score??0)>=.6}">{{qualityLabel(s)}}</span>
            <button class="remove-sample" :disabled="busy===s.id" @click="removeSample(p,s)">{{busy===s.id?t('product.people.deleting'):t('product.people.deleteSample')}}</button>
          </div>
        </div>
      </section>
    </article>
    <div v-if="!filtered.length" class="state-card"><b>{{query?t('product.people.noMatch'):t('product.people.emptyTitle')}}</b><span>{{query?t('product.people.noMatchHint'):t('product.people.empty')}}</span></div>
  </div>
  <aside class="privacy"><span>LOCAL</span><p>{{t('product.people.privacy')}}</p></aside>
</section></template>

<style scoped>
.people-create{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:16px;padding:18px;background:var(--ink-2);border:1px solid var(--border-soft);border-radius:10px}.people-create h2{font-size:16px}.people-create p{margin-top:5px;color:var(--text-3);font-size:12px}.people-tools{display:flex;justify-content:flex-end;gap:16px;margin-bottom:24px}.new-person{display:flex;max-width:520px;min-width:420px;flex:1}.new-person input,.filter{background:var(--ink-2);border:1px solid var(--border);padding:12px 14px}.new-person input{min-width:0;flex:1;border-radius:8px 0 0 8px}.new-person button{min-width:120px;padding:0 18px;background:var(--amber);color:var(--ink);border-radius:0 8px 8px 0;font-weight:700}.new-person button:disabled{opacity:.45}.filter{width:240px;border-radius:8px}.new-person input:focus,.filter:focus{border-color:var(--amber)}.inline-error,.inline-notice{display:flex;justify-content:space-between;padding:10px 12px;margin-bottom:16px;border-radius:7px}.inline-error{background:rgba(255,71,87,.1);color:var(--red)}.inline-notice{background:var(--teal-soft);color:var(--teal)}.sample-player{display:none}
.people-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}.people-grid>article{display:grid;grid-template-columns:48px minmax(120px,1fr) auto auto auto;align-items:center;gap:12px;padding:18px;background:var(--ink-2);border:1px solid var(--border-soft);border-radius:10px;transition:border-color .15s,background .15s}.people-grid>article.expanded{grid-column:1/-1;border-color:rgba(255,107,53,.38);background:linear-gradient(145deg,var(--ink-2),rgba(255,107,53,.025))}.avatar{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;background:var(--amber-soft);color:var(--amber);font:20px var(--serif)}.person-copy h3{font-size:15px}.person-copy p{color:var(--text-3);font:10px/1.4 var(--mono);margin-top:4px}.sample,.manage{padding:8px 10px;border:1px solid var(--border);border-radius:6px;font:10px var(--mono);cursor:pointer}.sample{color:var(--amber)}.sample input{display:none}.manage{color:var(--text-2)}.manage:hover{border-color:var(--text-3);color:var(--text)}.delete{color:var(--text-3);font-size:18px}.delete:hover{color:var(--red)}
.sample-actions{display:flex;gap:8px}.sample.record{color:var(--teal)}.sample.record:disabled{opacity:.45;cursor:not-allowed}
.recorder-panel{grid-column:1/-1;margin-top:6px;padding:14px 16px;background:var(--ink-3);border:1px solid var(--border-soft);border-radius:8px}.rec-hint{color:var(--text-3);font:10px var(--mono);margin-bottom:10px}.rec-row{display:flex;flex-wrap:wrap;align-items:center;gap:12px}.rec-timer{color:var(--teal);font:12px var(--mono)}.rec-player{width:100%;max-width:420px}.rec-actions{display:flex;gap:8px;margin-left:auto}.rec-actions button{padding:8px 14px;border:1px solid var(--border);border-radius:6px;font:10px var(--mono);cursor:pointer;color:var(--text-2)}.rec-actions button:hover{border-color:var(--text-3);color:var(--text)}.rec-actions .rec-confirm{background:var(--amber);color:var(--ink);border-color:var(--amber);font-weight:700}.rec-actions .rec-confirm:disabled{opacity:.45}.rec-stop{padding:8px 14px;border:1px solid var(--red);border-radius:6px;color:var(--red);font:10px var(--mono);cursor:pointer}
.sample-panel{grid-column:1/-1;margin-top:5px;padding-top:18px;border-top:1px solid var(--border-soft)}.sample-panel>header{display:flex;align-items:start;justify-content:space-between;margin-bottom:12px}.sample-panel h4{font:20px var(--serif)}.sample-panel header p{margin-top:3px;color:var(--text-3);font-size:11px}.sample-panel header>span{min-width:28px;padding:4px 7px;border:1px solid var(--border);border-radius:999px;text-align:center;color:var(--amber);font:10px var(--mono)}.sample-list{display:flex;flex-direction:column;gap:7px}.sample-row{display:grid;grid-template-columns:38px minmax(180px,1fr) auto auto;align-items:center;gap:12px;padding:12px 13px;background:var(--ink-3);border:1px solid var(--border-soft);border-radius:8px}.preview{width:34px;height:34px;display:grid;place-items:center;border:1px solid var(--border);border-radius:50%;color:var(--amber)}.preview:hover,.preview.playing{border-color:var(--amber);background:var(--amber-soft)}.preview:disabled{opacity:.5}.preview span{font:10px var(--mono)}.sample-copy{min-width:0}.sample-copy b{font-size:12px}.sample-copy p{margin-top:2px;color:var(--text-3);font:9px var(--mono)}.sample-copy code{display:block;max-width:360px;margin-top:4px;overflow:hidden;color:var(--text-3);font:8px var(--mono);text-overflow:ellipsis;white-space:nowrap}.quality{padding:4px 7px;border:1px solid rgba(212,165,116,.28);border-radius:4px;color:var(--gold);font:9px var(--mono)}.quality.good{border-color:rgba(78,205,196,.3);color:var(--teal)}.remove-sample{padding:7px 9px;color:var(--text-3);font:9px var(--mono)}.remove-sample:hover{color:var(--red)}.remove-sample:disabled{opacity:.45}.sample-empty{padding:30px;text-align:center;color:var(--text-3);border:1px dashed var(--border);border-radius:8px;font:10px var(--mono)}
.privacy{display:flex;gap:14px;margin-top:26px;padding:16px 18px;border-left:2px solid var(--teal);background:var(--teal-soft);color:var(--text-2)}.privacy span{color:var(--teal);font:9px var(--mono)}.state-card{grid-column:1/-1;min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;text-align:center;color:var(--text-3);border:1px dashed var(--border);border-radius:12px}.state-card b{color:var(--text);font:22px var(--serif)}
@media(max-width:760px){.people-create{align-items:stretch;flex-direction:column}.new-person{min-width:0;max-width:none}.people-tools{flex-direction:column}.filter{width:100%}.people-grid{grid-template-columns:1fr}.people-grid>article{grid-template-columns:44px 1fr auto}.manage{grid-row:2;grid-column:2}.sample-actions{grid-row:2;grid-column:3;flex-direction:column}.delete{grid-row:1;grid-column:3}.sample-row{grid-template-columns:38px 1fr auto}.quality{grid-column:2}.remove-sample{grid-column:3;grid-row:2}.privacy{align-items:flex-start}}
</style>
