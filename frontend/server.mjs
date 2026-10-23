import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, extname, sep } from 'node:path';
const root = fileURLToPath(new URL('./dist/', import.meta.url));
const port = Number(process.env.PORT || 5173);
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8' };
const server = http.createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (pathname.startsWith('/api/')) {
      const upstream = new URL(process.env.MCP_API_URL || 'http://127.0.0.1:8081');
      const proxy = http.request({ hostname: upstream.hostname, port: upstream.port || 80,
        path: req.url, method: req.method, headers: {
          'content-type': 'application/json', accept: 'application/json',
          ...(req.headers.authorization ? {authorization: req.headers.authorization} : {})
        } }, response => { res.writeHead(response.statusCode, {'Content-Type':'application/json', 'Cache-Control':'no-store'}); response.pipe(res); });
      proxy.setTimeout(185000, () => proxy.destroy());
      proxy.on('error', () => { if (!res.headersSent) res.writeHead(502, {'Content-Type':'application/json'}); res.end(JSON.stringify({error:{code:'MCP_UNAVAILABLE',message:'MCP 서버 연결을 확인해 주세요.'}})); });
      req.on('aborted', () => proxy.destroy());
      req.pipe(proxy); return;
    }
    const file = resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);
    if (!file.startsWith(root.endsWith(sep) ? root : `${root}${sep}`)) { res.writeHead(403); res.end('Forbidden'); return; }
    const data = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(data);
  } catch { res.writeHead(404); res.end('Not found'); }
});
server.listen(port, '127.0.0.1', () => console.log(`Local: http://localhost:${server.address().port}`));
