import { createRouter, createWebHistory } from 'vue-router'
import WorkspaceLayout from '../layouts/WorkspaceLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: WorkspaceLayout,
      children: [
        {
          path: '',
          name: 'workspace',
          component: () => import('../views/WorkspaceView.vue'),
        },
      ],
    },
  ],
})

export default router
