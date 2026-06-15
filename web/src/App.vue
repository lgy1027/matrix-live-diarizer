<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AppNav from './components/AppNav.vue'
import AppBar from './components/AppBar.vue'
import ToastHost from './components/ToastHost.vue'
import PwdChangeGuard from './components/PwdChangeGuard.vue'
import DialogProvider from './components/DialogProvider.vue'

const route = useRoute()
const auth = useAuthStore()

const showPwdGuard = computed(() => auth.isLoggedIn && auth.mustChangePwd)
const showChrome = computed(() => route.name !== 'login')
</script>

<template>
  <DialogProvider>
    <div class="app" v-if="showChrome">
      <AppNav />
      <main class="col">
        <AppBar />
        <RouterView v-slot="{ Component }">
          <transition name="view" mode="out-in">
            <component :is="Component" />
          </transition>
        </RouterView>
      </main>
    </div>
    <RouterView v-else />

    <ToastHost />
    <PwdChangeGuard v-if="showPwdGuard" />
  </DialogProvider>
</template>

<style>
.app {
  display: grid;
  grid-template-columns: 56px 1fr;
  grid-template-rows: 1fr;
  height: 100vh;
}
.col {
  display: grid;
  grid-template-rows: auto 1fr auto;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  height: 100vh;
  overflow: hidden;
}
.col > :nth-child(2) {
  /* RouterView 容器: 可滚动 */
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}
.view-enter-active,
.view-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.view-enter-from { opacity: 0; transform: translateY(6px); }
.view-leave-to { opacity: 0; transform: translateY(-6px); }
</style>
