<script setup>
defineProps({
  records: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
});
</script>

<template>
  <section class="table-panel">
    <div class="panel-title">
      <div>
        <h3>原始监测记录</h3>
        <p>保留上游字段名，便于现场排查和接口联调。</p>
      </div>
      <span>{{ records.length }} 条</span>
    </div>
    <el-table
      v-loading="loading"
      :data="records"
      height="420"
      border
      stripe
      class="monitor-table"
      empty-text="暂无数据"
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
  </section>
</template>
