export type View = 'chord'|'single'|'sankey'|'compare'|'heatmap';
export type VisaGroup = 'visitor'|'student'|'work'|'family'|'other'|'unclassified';
export interface Entity {code:string;name:string;region?:string;kind?:string;members?:string[];}
export interface WorkbenchState {
 countries:string[];focusCountry:string;year:number;visaGroups:VisaGroup[];
 spatialScale:'country'|'region';flowScope:'internal'|'connected';regionMode:'aggregate'|'members';view:View;
 singleMode:'radial'|'origins'|'destinations'|'categories';direction:'both'|'incoming'|'outgoing';
 motionMode:'analysis'|'presentation';playing:boolean;playbackSpeed:number;flowLight:boolean;showFree:boolean;maxNodes:number;minAmount:number;
}
export interface AnalysisEdge {id:string;origin:string;destination:string;amount:number;count:number;ids:string[];visaGroup?:VisaGroup;groups:Partial<Record<VisaGroup,number>>;}
export interface AnalysisNode {code:string;name:string;incoming:number;outgoing:number;net:number|null;incomingKnown:boolean;outgoingKnown:boolean;unallocated:number;selected:boolean;}
export interface CategoryTotal {group:VisaGroup;name:string;incoming:number;outgoing:number;}
export interface CoverageRecord {code:string;name:string;region:string;year:number;visa_group:string;status:string;fee_known:boolean;fee_current_snapshot_known?:boolean;quantity_known:boolean;quantity_context_known?:boolean;mobility_context_known?:boolean;amount_known:boolean;nationality_known:boolean;source_ids:string[];notes:string;}
export interface AnalysisResult {
 comparisonYear?:number;previousNodes?:AnalysisNode[];edges:AnalysisEdge[];nodes:AnalysisNode[];entities:Entity[];countryTotals:AnalysisNode[];
 total:number;globalTotal:number;year:number;categoryTotals:CategoryTotal[];coverage:CoverageRecord[];
 totals:{internal:number;externalIn:number;externalOut:number;unallocated:number;amount:number;rowCount:number;edgeCount:number;};
}
export interface ChartProps {analysis:AnalysisResult;state:WorkbenchState;width:number;height:number;onFocus:(code:string)=>void;onRoute:(origin:string,destination:string)=>void;onState:(patch:Partial<WorkbenchState>)=>void;reducedMotion:boolean;}
export type IndexTuple=[number,number,number,number,number,number,number];
export interface EventBenchmark {label:string;basis:string;quantity:number;amount_cny:number;fee_per_event_cny:number;amount_share:number|null;rows:number;notes:string;source_ids:string[];}
export interface ProfileDirection {amount_bases?:{key:string;label:string;amount_cny:number;rows:number}[];amount_cny:number|null;counterparts:number;top_code:string|null;top_amount_cny:number|null;unallocated_cny:number;benchmark:EventBenchmark|null;source_ids:string[];}
export interface CountryProfile {code:string;year:number;available_years:number[];population:{year:number;value:number;basis:string;label:string;source_id:string;is_estimate:boolean}|null;incoming:ProfileDirection;outgoing:ProfileDirection;}
export interface CountryContextPoint {original_value?:string|number;original_unit?:string;source_rounding_unit?:number;source_rounding_half_unit?:number;year:number;period_start:string;period_end:string;value:number;lower?:number;upper?:number;bound_type?:string;lower_inclusive?:boolean;upper_inclusive?:boolean;calculation_type?:string;source_id:string;observation_id:string;source_locator?:string;source_status?:string;source_status_label?:string;aggregation_role?:string;quality_issue?:string;context_selection_default?:boolean;}
export interface CountryContextPartner {code:string;name:string;points:CountryContextPoint[];}
export interface CountryContextSeries {id:string;native_series_id?:string;label:string;domain:string;metric:string;unit:string;unit_label:string;origin_basis?:string;origin_basis_label:string;period_type:string;visa_type?:string;scope?:string;flow_direction?:string;notes:string;source_ids:string[];partners:CountryContextPartner[];quality_issue?:string;context_selection_default?:boolean;}
export interface CountryContextData {schema:string;code:string;name:string;series:CountryContextSeries[];}
export interface CountryContextManifest {file:string;years:number[];series_count:number;source_ids:string[];}
export interface WorkbenchIndex {meta:Record<string,any>;entities:Entity[];groups:VisaGroup[];records:IndexTuple[];schengenMembers:string[];coverage:CoverageRecord[];annualRanges:any[];chunks:Record<string,string>;sources:any[];models:any[];feeRules:any[];bills:any[];finances:any[];countryProfiles?:Record<string,Record<string,CountryProfile>>;countryContext?:Record<string,CountryContextManifest>;}
