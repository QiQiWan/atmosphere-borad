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
    <div class="metric-hint">{{ hint || '实时监测' }}</div>
  </div>
</template>
