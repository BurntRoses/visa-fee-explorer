import {ChordPlot} from './Chord';
import type {PlotProps} from './common';
import type {GraphData} from './helpers';

export function SinglePlot(p:PlotProps&{graph?:GraphData}){
 return <ChordPlot {...p} focus={p.state.focusCountry||p.state.countries[0]}/>;
}
