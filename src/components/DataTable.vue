<script setup>
import { computed, ref, watch } from 'vue';

const props = defineProps({
  records: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});

const currentPage = ref(1);
const pageSize = ref(100);

const total = computed(() => (Array.isArray(props.records) ? props.records.length : 0));
const pagedRecords = computed(() => {
  const rows = Array.isArray(props.records) ? props.records : [];
  const start = (currentPage.value - 1) * pageSize.value;
  return rows.slice(start, start + pageSize.value);
});
const pageStart = computed(() => (total.value === 0 ? 0 : (currentPage.value - 1) * pageSize.value + 1));
const pageEnd = computed(() => Math.min(currentPage.value * pageSize.value, total.value));

watch(
  () => props.records,
  () => {
    currentPage.value = 1;
  },
  { deep: false },
);
</script>

<template>
  <section class="table-panel">
    <div class="panel-title">
      <div>
        <h3>原始监测记录</h3>
      </div>
      <span>{{ total }} 条</span>
    </div>
    <el-table
      v-loading="loading"
      :data="pagedRecords"
      height="420"
      border
      stripe
      class="monitor-table"
      empty-text="暂无数据"
      table-layout="fixed"
    >
      <el-table-column prop="create_time" label="采集时间" min-width="165" fixed />
      <el-table-column prop="wendu" label="温度" width="86" />
      <el-table-column prop="shidu" label="湿度" width="86" />
      <el-table-column prop="fengsu" label="风速" width="86" />
      <el-table-column prop="fengxiang" label="风向" width="86" />
      <el-table-column prop="pm25" label="PM2.5" width="92" />
      <el-table-column prop="pm10" label="PM10" width="92" />
      <el-table-column prop="yuliang" label="雨量" width="86" />
      <el-table-column prop="yuqiang" label="雨强" width="86" />
      <el-table-column prop="nengjiandu" label="能见度" width="100" />
      <el-table-column prop="guangqiang" label="光强" width="90" />
      <el-table-column prop="dianliu" label="电流" width="86" />
      <el-table-column prop="dianya" label="电压" width="86" />
      <el-table-column prop="guangdian" label="光电" width="86" />
      <el-table-column prop="fengdian" label="风电" width="86" />
      <el-table-column prop="yadian" label="压电" width="86" />
      <el-table-column prop="jiebin" label="结冰" width="78" />
      <el-table-column prop="shuimo" label="水膜" width="78" />
      <el-table-column prop="jixue" label="积雪" width="78" />
    </el-table>
    <div class="table-footer" v-if="total > 0">
      <span>当前渲染 {{ pageStart }}–{{ pageEnd }} 条，避免一次性渲染全部记录造成卡顿。</span>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[50, 100, 200, 500]"
        :total="total"
        layout="sizes, prev, pager, next"
        small
        background
      />
    </div>
  </section>
</template>
