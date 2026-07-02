import { createRouter, createWebHistory } from 'vue-router';
import BoardView from '@/views/BoardView.vue';

export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'board',
      component: BoardView,
    },
  ],
});
