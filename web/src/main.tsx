import React from 'react';
import {createRoot} from 'react-dom/client';
import {App} from './App';
import './estilo.css';

createRoot(document.getElementById('raiz')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
