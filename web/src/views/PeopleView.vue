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

const {t}=useI18n(),dialog=useDialog()
const items=ref<Person[]>([]),details=ref<Record<string,PersonDetail>>({})
const name=ref(''),busy=ref(''),loading=ref(true),error=ref(''),notice=ref(''),query=ref('')
const expanded=ref(new Set<string>()),detailLoading=ref(''),samplePlayer=ref<HTMLAudioElement|null>(null)
const previewId=ref(''),previewUrl=ref(''),previewPlaying=ref(false),previewLoading=ref('')
const filtered=computed(()=>{const q=query.value.trim().toLocaleLowerCase();return q?items.value.filter(p=>p.name.toLocaleLowerCase().includes(q)):items.value})

async function load(){loading.value=true;try{items.value=(await listPeople()).items;error.value=''}catch(e){error.value=e instanceof Error?e.message:String(e)}finally{loading.value=false}}
async function loadDetail(personId:string){detailLoading.value=personId;try{details.value={...details.value,[personId]:await getPerson(personId)}}finally{detailLoading.value=''}}
async function toggleDetails(personId:string){const next=new Set(expanded.value);if(next.has(personId)){next.delete(personId)}else{next.add(personId);if(!details.value[personId])await loadDetail(personId)}expanded.value=next}
async function add(){const value=name.value.trim();if(!value)return;busy.value='new';error.value='';notice.value='';try{const person=await createPerson(value);name.value='';notice.value=t('product.people.created',{name:person.name});await load()}catch(e){error.value=e instanceof Error?e.message:String(e)}finally{busy.value=''}}
async function remove(p:Person){const ok=await dialog.showConfirm({title:t('product.people.deleteTitle'),message:t('product.people.deleteConfirm',{name:p.name}),confirmText:t('product.people.delete'),cancelText:t('btn.cancel'),danger:true});if(!ok)return;error.value='';notice.value='';try{stopPreview();await deletePerson(p.id);delete details.value[p.id];await load()}catch(e){error.value=e instanceof Error?e.message:String(e)}}
async function sample(p:Person,e:Event){const input=e.target as HTMLInputElement,f=input.files?.[0];if(!f)return;busy.value=p.id;error.value='';notice.value='';try{await uploadVoiceSample(p.id,f);notice.value=t('product.people.sampleAdded',{name:p.name});await Promise.all([load(),loadDetail(p.id)]);const next=new Set(expanded.value);next.add(p.id);expanded.value=next}catch(reason){error.value=reason instanceof Error?reason.message:String(reason)}finally{busy.value='';input.value=''}}
async function removeSample(p:Person,s:VoiceSample){const ok=await dialog.showConfirm({title:t('product.people.deleteSampleTitle'),message:t('product.people.deleteSampleConfirm',{name:p.name,seconds:s.duration_sec.toFixed(1)}),detail:t('product.people.deleteSampleImpact'),confirmText:t('product.people.deleteSample'),cancelText:t('btn.cancel'),danger:true});if(!ok)return;busy.value=s.id;error.value='';notice.value='';try{if(previewId.value===s.id)stopPreview();await deleteVoiceSample(p.id,s.id);notice.value=t('product.people.sampleDeleted');await Promise.all([load(),loadDetail(p.id)])}catch(reason){error.value=reason instanceof Error?reason.message:String(reason)}finally{busy.value=''}}
async function togglePreview(p:Person,s:VoiceSample){const player=samplePlayer.value;if(!player)return;if(previewId.value===s.id&&previewUrl.value){player.paused?await player.play():player.pause();return}previewLoading.value=s.id;try{stopPreview();previewUrl.value=await getVoiceSampleAudioUrl(p.id,s.id);previewId.value=s.id;await nextTick();await samplePlayer.value?.play()}catch(reason){error.value=reason instanceof Error?reason.message:String(reason);stopPreview()}finally{previewLoading.value=''}}
function stopPreview(){samplePlayer.value?.pause();if(previewUrl.value)URL.revokeObjectURL(previewUrl.value);previewUrl.value='';previewId.value='';previewPlaying.value=false}
function qualityLabel(s:VoiceSample){return s.quality_score==null?t('product.people.qualityUnknown'):t('product.people.quality',{score:Math.round(s.quality_score*100)})}
function dateLabel(value:string){const date=new Date(value);return Number.isNaN(date.getTime())?'—':date.toLocaleDateString()}
onMounted(load)
onBeforeUnmount(stopPreview)
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
      <label class="sample"><input type="file" accept="audio/*" @change="sample(p,$event)">{{busy===p.id?t('product.people.processing'):t('product.people.addSample')}}</label>
      <button class="delete" :aria-label="t('product.people.delete')" @click="remove(p)">×</button>
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
.sample-panel{grid-column:1/-1;margin-top:5px;padding-top:18px;border-top:1px solid var(--border-soft)}.sample-panel>header{display:flex;align-items:start;justify-content:space-between;margin-bottom:12px}.sample-panel h4{font:20px var(--serif)}.sample-panel header p{margin-top:3px;color:var(--text-3);font-size:11px}.sample-panel header>span{min-width:28px;padding:4px 7px;border:1px solid var(--border);border-radius:999px;text-align:center;color:var(--amber);font:10px var(--mono)}.sample-list{display:flex;flex-direction:column;gap:7px}.sample-row{display:grid;grid-template-columns:38px minmax(180px,1fr) auto auto;align-items:center;gap:12px;padding:12px 13px;background:var(--ink-3);border:1px solid var(--border-soft);border-radius:8px}.preview{width:34px;height:34px;display:grid;place-items:center;border:1px solid var(--border);border-radius:50%;color:var(--amber)}.preview:hover,.preview.playing{border-color:var(--amber);background:var(--amber-soft)}.preview:disabled{opacity:.5}.preview span{font:10px var(--mono)}.sample-copy{min-width:0}.sample-copy b{font-size:12px}.sample-copy p{margin-top:2px;color:var(--text-3);font:9px var(--mono)}.sample-copy code{display:block;max-width:360px;margin-top:4px;overflow:hidden;color:var(--text-3);font:8px var(--mono);text-overflow:ellipsis;white-space:nowrap}.quality{padding:4px 7px;border:1px solid rgba(212,165,116,.28);border-radius:4px;color:var(--gold);font:9px var(--mono)}.quality.good{border-color:rgba(78,205,196,.3);color:var(--teal)}.remove-sample{padding:7px 9px;color:var(--text-3);font:9px var(--mono)}.remove-sample:hover{color:var(--red)}.remove-sample:disabled{opacity:.45}.sample-empty{padding:30px;text-align:center;color:var(--text-3);border:1px dashed var(--border);border-radius:8px;font:10px var(--mono)}
.privacy{display:flex;gap:14px;margin-top:26px;padding:16px 18px;border-left:2px solid var(--teal);background:var(--teal-soft);color:var(--text-2)}.privacy span{color:var(--teal);font:9px var(--mono)}.state-card{grid-column:1/-1;min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;text-align:center;color:var(--text-3);border:1px dashed var(--border);border-radius:12px}.state-card b{color:var(--text);font:22px var(--serif)}
@media(max-width:760px){.people-create{align-items:stretch;flex-direction:column}.new-person{min-width:0;max-width:none}.people-tools{flex-direction:column}.filter{width:100%}.people-grid{grid-template-columns:1fr}.people-grid>article{grid-template-columns:44px 1fr auto}.manage,.sample{grid-row:2}.manage{grid-column:2}.sample{grid-column:3}.delete{grid-row:1;grid-column:3}.sample-row{grid-template-columns:38px 1fr auto}.quality{grid-column:2}.remove-sample{grid-column:3;grid-row:2}.privacy{align-items:flex-start}}
</style>
