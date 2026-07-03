<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '--' },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
});
</script>

<template>
  <div class="metric-card">
    <div class="metric-label">{{ label }}</div>
    <div class="metric-value">
      <span>{{ value ?? '--' }}</span>
      <small v-if="unit">{{ unit }}</small>
    </div>
    <div v-if="hint" class="metric-hint">{{ hint }}</div>
  </div>
</template>
