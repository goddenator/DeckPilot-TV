import type { ReactNode, ChangeEvent } from 'react';
export function ButtonItem({children,description,disabled,onClick}:{children?:ReactNode;description?:ReactNode;disabled?:boolean;onClick?:()=>void}){
  return <button disabled={disabled} onClick={onClick} style={{display:'block',width:'100%',padding:12,textAlign:'left',border:'1px solid #506172',borderRadius:8,color:'#f5f8fa',background:'#223345',fontSize:16}}><span>{children}</span>{description&&<small aria-hidden="true" style={{display:'block',marginTop:6,opacity:.8}}>{description}</small>}</button>;
}
export function PanelSection({title,children}:{title?:string;children?:ReactNode}){return <section style={{padding:'8px 16px'}}>{title&&<h2>{title}</h2>}{children}</section>;}
export function PanelSectionRow({children}:{children:ReactNode}){return <div style={{marginBottom:8}}>{children}</div>;}
export function TextField({label,value,onChange}:{label:string;value:string;onChange:(e:ChangeEvent<HTMLInputElement>)=>void}){return <label>{label}<input style={{boxSizing:'border-box',width:'100%',padding:12,fontSize:18,marginTop:8}} value={value} onChange={onChange}/></label>;}
export const Navigation={Navigate:(url:string)=>{document.body.dataset.deckyRoute=url;},NavigateToExternalWeb:(url:string)=>{document.body.dataset.openedUrl=url;}};
