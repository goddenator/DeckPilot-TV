declare global { interface Window { bridge:(name:string,args:unknown[])=>Promise<unknown>; } }
export const callable=(name:string)=>(...args:unknown[])=>window.bridge(name,args);

export const definePlugin=<T,>(factory:()=>T)=>factory;
