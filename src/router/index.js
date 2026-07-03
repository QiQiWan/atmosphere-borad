import { createRouter, createWebHistory } from 'vue-router';
import BoardView from '@/views/BoardView.vue';
import CacheAdminView from '@/views/CacheAdminView.vue';

export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'board',
      component: BoardView,
    },
    {
      path: '/cache-admin',
      name: 'cache-admin',
      component: CacheAdminView,
    },
  ],
});
