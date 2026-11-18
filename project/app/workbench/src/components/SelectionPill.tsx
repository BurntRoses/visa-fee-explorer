// Adapted from 前端处方 / components/studio/SelectionPill.tsx.
import {motion} from 'motion/react';
import {useSystemReducedMotion} from '../hooks/useSystemReducedMotion';
export function SelectionPill(){const reduced=useSystemReducedMotion();return <motion.span aria-hidden="true" className="selection-surface" layoutId="selection" transition={reduced?{duration:0}:{type:'spring',stiffness:430,damping:34}}/>;}
