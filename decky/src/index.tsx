import { definePlugin } from '@decky/api';
import { FaGamepad } from 'react-icons/fa';
import { DeckPilotApp } from './App';

export default definePlugin(()=>({name:'DeckPilot TV',titleView:<div>DeckPilot</div>,content:<DeckPilotApp/>,icon:<FaGamepad/>}));
