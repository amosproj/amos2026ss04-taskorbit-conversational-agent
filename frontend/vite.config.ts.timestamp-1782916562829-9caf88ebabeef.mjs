// vite.config.ts
import path from "node:path";
import tailwindcss from "file:///Users/shikharthakur/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent/frontend/node_modules/@tailwindcss/vite/dist/index.mjs";
import react from "file:///Users/shikharthakur/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent/frontend/node_modules/@vitejs/plugin-react/dist/index.js";
import { defineConfig, loadEnv } from "file:///Users/shikharthakur/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent/frontend/node_modules/vite/dist/node/index.js";
var __vite_injected_original_dirname = "/Users/shikharthakur/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent/frontend";
var vite_config_default = defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__vite_injected_original_dirname, "./src")
      }
    },
    server: {
      host: true,
      // listen on 0.0.0.0 so Docker port-forwarding works
      port: 5173,
      strictPort: true,
      watch: {
        usePolling: true
      },
      // Proxy backend calls during development so the frontend can use
      // relative URLs like `/api/health` and avoid CORS hassle.
      proxy: {
        "/api": {
          target: process.env.VITE_API_URL ?? env.VITE_API_URL ?? "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, "")
        }
      }
    }
  };
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvVXNlcnMvc2hpa2hhcnRoYWt1ci9Eb2N1bWVudHMvR2l0SHViL2Ftb3MyMDI2c3MwNC10YXNrb3JiaXQtY29udmVyc2F0aW9uYWwtYWdlbnQvZnJvbnRlbmRcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIi9Vc2Vycy9zaGlraGFydGhha3VyL0RvY3VtZW50cy9HaXRIdWIvYW1vczIwMjZzczA0LXRhc2tvcmJpdC1jb252ZXJzYXRpb25hbC1hZ2VudC9mcm9udGVuZC92aXRlLmNvbmZpZy50c1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vVXNlcnMvc2hpa2hhcnRoYWt1ci9Eb2N1bWVudHMvR2l0SHViL2Ftb3MyMDI2c3MwNC10YXNrb3JiaXQtY29udmVyc2F0aW9uYWwtYWdlbnQvZnJvbnRlbmQvdml0ZS5jb25maWcudHNcIjtpbXBvcnQgcGF0aCBmcm9tIFwibm9kZTpwYXRoXCI7XG5cbmltcG9ydCB0YWlsd2luZGNzcyBmcm9tIFwiQHRhaWx3aW5kY3NzL3ZpdGVcIjtcbmltcG9ydCByZWFjdCBmcm9tIFwiQHZpdGVqcy9wbHVnaW4tcmVhY3RcIjtcbmltcG9ydCB7IGRlZmluZUNvbmZpZywgbG9hZEVudiB9IGZyb20gXCJ2aXRlXCI7XG5cbi8vIGh0dHBzOi8vdml0ZS5kZXYvY29uZmlnL1xuZXhwb3J0IGRlZmF1bHQgZGVmaW5lQ29uZmlnKCh7IG1vZGUgfSkgPT4ge1xuICBjb25zdCBlbnYgPSBsb2FkRW52KG1vZGUsIHByb2Nlc3MuY3dkKCksIFwiXCIpO1xuXG4gIHJldHVybiB7XG4gICAgcGx1Z2luczogW3JlYWN0KCksIHRhaWx3aW5kY3NzKCldLFxuICAgIHJlc29sdmU6IHtcbiAgICAgIGFsaWFzOiB7XG4gICAgICAgIFwiQFwiOiBwYXRoLnJlc29sdmUoX19kaXJuYW1lLCBcIi4vc3JjXCIpLFxuICAgICAgfSxcbiAgICB9LFxuICAgIHNlcnZlcjoge1xuICAgICAgaG9zdDogdHJ1ZSwgLy8gbGlzdGVuIG9uIDAuMC4wLjAgc28gRG9ja2VyIHBvcnQtZm9yd2FyZGluZyB3b3Jrc1xuICAgICAgcG9ydDogNTE3MyxcbiAgICAgIHN0cmljdFBvcnQ6IHRydWUsXG4gICAgICB3YXRjaDoge1xuICAgICAgICB1c2VQb2xsaW5nOiB0cnVlLFxuICAgICAgfSxcbiAgICAgIC8vIFByb3h5IGJhY2tlbmQgY2FsbHMgZHVyaW5nIGRldmVsb3BtZW50IHNvIHRoZSBmcm9udGVuZCBjYW4gdXNlXG4gICAgICAvLyByZWxhdGl2ZSBVUkxzIGxpa2UgYC9hcGkvaGVhbHRoYCBhbmQgYXZvaWQgQ09SUyBoYXNzbGUuXG4gICAgICBwcm94eToge1xuICAgICAgICBcIi9hcGlcIjoge1xuICAgICAgICAgIHRhcmdldDogcHJvY2Vzcy5lbnYuVklURV9BUElfVVJMID8/IGVudi5WSVRFX0FQSV9VUkwgPz8gXCJodHRwOi8vMTI3LjAuMC4xOjgwMDBcIixcbiAgICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXG4gICAgICAgICAgcmV3cml0ZTogKHApID0+IHAucmVwbGFjZSgvXlxcL2FwaS8sIFwiXCIpLFxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9LFxuICB9O1xufSk7XG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQWdjLE9BQU8sVUFBVTtBQUVqZCxPQUFPLGlCQUFpQjtBQUN4QixPQUFPLFdBQVc7QUFDbEIsU0FBUyxjQUFjLGVBQWU7QUFKdEMsSUFBTSxtQ0FBbUM7QUFPekMsSUFBTyxzQkFBUSxhQUFhLENBQUMsRUFBRSxLQUFLLE1BQU07QUFDeEMsUUFBTSxNQUFNLFFBQVEsTUFBTSxRQUFRLElBQUksR0FBRyxFQUFFO0FBRTNDLFNBQU87QUFBQSxJQUNMLFNBQVMsQ0FBQyxNQUFNLEdBQUcsWUFBWSxDQUFDO0FBQUEsSUFDaEMsU0FBUztBQUFBLE1BQ1AsT0FBTztBQUFBLFFBQ0wsS0FBSyxLQUFLLFFBQVEsa0NBQVcsT0FBTztBQUFBLE1BQ3RDO0FBQUEsSUFDRjtBQUFBLElBQ0EsUUFBUTtBQUFBLE1BQ04sTUFBTTtBQUFBO0FBQUEsTUFDTixNQUFNO0FBQUEsTUFDTixZQUFZO0FBQUEsTUFDWixPQUFPO0FBQUEsUUFDTCxZQUFZO0FBQUEsTUFDZDtBQUFBO0FBQUE7QUFBQSxNQUdBLE9BQU87QUFBQSxRQUNMLFFBQVE7QUFBQSxVQUNOLFFBQVEsUUFBUSxJQUFJLGdCQUFnQixJQUFJLGdCQUFnQjtBQUFBLFVBQ3hELGNBQWM7QUFBQSxVQUNkLFNBQVMsQ0FBQyxNQUFNLEVBQUUsUUFBUSxVQUFVLEVBQUU7QUFBQSxRQUN4QztBQUFBLE1BQ0Y7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUNGLENBQUM7IiwKICAibmFtZXMiOiBbXQp9Cg==
