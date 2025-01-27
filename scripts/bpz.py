"""
   bpz: Bayesian Photo-Z estimation
   Reference: Benitez 2000, ApJ, 536, p.571
   Usage:
   python bpz.py catalog.cat 
   Needs a catalog.columns file which describes the contents of catalog.cat

Todo: Fix ID column, output to fits / hdf5 file(s) (hdf5 better because it can be done line by line).
There's no point in this right now. Non-detections are cut out anyway! ffs
Even BPZ clips them - why? And why does changing the flux norm matter - mags are converted to arbitrary flux scaling anyway.
So, we will implement fits input in mags. How disappointing.
In fluxes the systematic mag error doesn't make any sense.
Why are the odds gettig messed up? might be the z_thru parameter.

NOTE: We have added two *required* environment variables!!!  BPZ will fail if these are not set!


BPZDATAPATH: The file path to the directory containing the SED, FILTER, and AB directories.
You can set either external to python with e.g. (in bash):
`export BPZDATAPATH=/global/homes/u/user/software/DESC_BPZ`
or you can set within python with, e.g.:
"""

import desc_bpz
from desc_bpz.useful_py3 import *
rolex=watch()
rolex.set()

#from Numeric import *
from numpy import *
from desc_bpz.bpz_tools_py3 import *
from string import *
import os,glob,sys
import time 
import pickle
import shelve
import h5py
from desc_bpz.will_tools_py3 import *
from desc_bpz.paths import get_fil_file, get_sed_file, get_ab_file
from desc_bpz.paths import set_fil_dir, set_sed_dir, set_ab_dir
from desc_bpz.coetools_py3 import pause, params_cl
import scipy
from scipy.interpolate import interp1d

print('RAUL\'S VERSION')

def seglist(vals, mask=None):
    """Split vals into lists based on mask > 0"""
    if mask == None:
        mask = greater(vals, 0)
    lists = []
    i = 0
    lastgood = False
    list1 = []
    for i in range(len(vals)):
        if mask[i] == False:
            if lastgood:
                lists.append(list1)
                list1 = []
            lastgood = False
        if mask[i]:
            list1.append(vals[i])
            lastgood = True
    
    if lastgood:
        lists.append(list1)
    return lists

# Initialization and definitions#

#Current directory
homedir=os.getcwd()

#Parameter definition 
pars=params()

pars.d={
    'SPECTRA':'CWWSB4_6.list', # template list 
    'PRIOR':   'hdfn_gen',      # prior name                                                             
#    'PRIOR':   'cosmos_Laigle_py3',      # prior name
    #'PRIOR':   'sva1_weights',      # prior name
#    'PRIOR':   'y1a1_test',      # prior name
    'NTYPES':None,  # Number of Elliptical, Spiral, and Starburst/Irregular templates  Default: 1,2,n-3
    'DZ':      0.01,        # redshift resolution
    'ZMIN':    0.01,        # minimum redshift
    'ZMAX':    10.0,         # maximum redshift
    'MAG':     'yes',       # Data in magnitudes?
    'FLUX_ZP': 30.,        # for converting m_0 and adjusting fluxes to AB scale from flux to mags.
    'MIN_MAGERR':   0.001,   # minimum magnitude uncertainty --DC
    'ODDS': 0.95,           # Odds threshold: affects confidence limits definition
    'INTERP': 0,            # Number of interpolated templates between each of the original ones
    'EXCLUDE': 'none',      # Filters to be excluded from the estimation
    'NEW_AB': 'no',         # If yes, generate new AB files even if they already exist
    'CHECK': 'yes',          # Perform some checks, compare observed colors with templates, etc.
    'VERBOSE': 'yes',       # Print estimated redshifts to the standard output
    'PROBS': 'no',          # Save all the galaxy probability distributions (it will create a very large file)
    'PROBS2': 'no',         # Save all the galaxy probability distributions P(z,t) (but not priors) -- Compact
    'PROBS_LITE': 'yes',    # Save only the final probability distribution
    'SAMPLING': 'no',       # Save random photo-z sampled from object posterior PDF
    'NSAMPLES': 1,	    # Number of random samples drawn for each object
    'SEED': 42,          # Seed for random sample
    'Z_MEAN': 'yes',         # Get mean redshift of galaxy N(z)
    'Z_SIG': 'yes',          # Get standard deviation of galaxy N(z)
    'GET_Z': 'yes',         # Actually obtain photo-z
    'ONLY_TYPE':'no',       # Use spectroscopic redshifts instead of photo-z
    'MADAU':'yes',          #Apply Madau correction to spectra
    'Z_THR':0,              #Integrate probability for z>z_thr
    'COLOR':'no',           #Use colors instead of fluxes
    'PLOTS':'no',           #Don't produce plots 
    'INTERACTIVE':'yes',     #Don't query the user
    'PHOTO_ERRORS':'no',    #Define the confidence interval using only the photometric errors
    'MIN_RMS':0.05,         #"Intrinsic"  photo-z rms in dz /(1+z) (Change to 0.05 for templates from Benitez et al. 2004
    'N_PEAKS':1,
    'MERGE_PEAKS':'no',
    'CONVOLVE_P':'yes',
    'P_MIN':1e-2,
    'SED_DIR': get_sed_file(''),
    'AB_DIR': get_ab_file(''),
    #'AB_DIR': '/home/will/work/bpz-1.99.3/ABcorr', ### THIS PATH NEEDS SETTING
    'FILTER_DIR': get_fil_file(''),
    'DELTA_M_0': 0.,
    'ZP_OFFSETS':0.,
    'ZC': None,
    'FC':None,
    "ADD_SPEC_PROB":None,
    "ADD_CONTINUOUS_PROB":None,
    "NMAX": None, # Useful for testing
    "WRITE_FLUX_COMP": 'no', #flag to write flux_comparison file use 'no' rather than False in keepint with BPZ formatting
    "H5_CHUNK_SIZE": 10000, #how big of hdf5 chunks to create at a time
    "OUTPUT_CUT": "Null"
}               


if pars.d['PLOTS']=='no': plots=0
if pars.d['WRITE_FLUX_COMP'] == 'no': write_flux_comp = False
    

if plots:
    # If pylab installed show plots
    plots='pylab'
    try:
        import matplotlib
        matplotlib.use('TkAgg')
        from pylab import *
        # from coeplot2a import *
        plot([1])
        title('KILL THIS WINDOW!')
        show()
        ioff()
    except:
        try:
            from biggles import *
            plots='biggles'
        except:
            plots=0

#Define the default values of the parameters 
pars.d['INPUT']=sys.argv[1]       # catalog with the photometry
obs_file=pars.d['INPUT']
root=os.path.splitext(pars.d['INPUT'])[0]
pars.d['COLUMNS']=root+'.columns' # column information for the input catalog
pars.d['OUTPUT']= root+'.bpz.h5'     # output 

nargs=len(sys.argv)

ipar=2

if nargs>2: #Check for parameter file and update parameters
    if  sys.argv[2]=='-P': 
        pars.fromfile(sys.argv[3])
        ipar=4

# Update the parameters using command line additions
#pars.fromcommandline(sys.argv[ipar:]) 
#for key in pars.d:
#    print key, pars.d[key]
#pause()
pars.d.update(params_cl())  # allows for flag only (no value after), e.g., -CHECK

chunksize = int(pars.d['H5_CHUNK_SIZE'])
print ("chunksize: %d" %chunksize)


def updateblank(var, ext):
    global pars
    if pars.d[var] in [None, 'yes']:
        pars.d[var] = root+'.'+ext

updateblank('CHECK', 'flux_comparison')
updateblank('PROBS_LITE', 'probs.h5')
updateblank('PROBS', 'full_probs')
updateblank('PROBS2', 'chisq')

#if pars.d['CHECK'] in [None, 'yes']:
#    pars.d['CHECK'] = root+'.flux_comparison'

#This allows to change the auxiliary directories used by BPZ
if pars.d['SED_DIR']!=get_sed_file(''):
    print(("Changing sed_dir to ",pars.d['SED_DIR'])) 
    set_sed_dir(pars.d['SED_DIR'])

if pars.d['AB_DIR']!=get_ab_file(''):
    print("Changing ab_dir to ",pars.d['AB_DIR']) 
    set_ab_dir(pars.d['AB_DIR'])


if pars.d['FILTER_DIR']!=get_fil_file(''):
    print("Changing fil_dir to ",pars.d['FILTER_DIR']) 
    set_fil_dir(pars.d['FILTER_DIR'])



#Better safe than sorry
if pars.d['OUTPUT']==obs_file or pars.d['PROBS']==obs_file or pars.d['PROBS2']==obs_file or pars.d['PROBS_LITE']==obs_file:
    print("This would delete the input file!")
    sys.exit()
if pars.d['OUTPUT']==pars.d['COLUMNS'] or pars.d['PROBS_LITE']==pars.d['COLUMNS'] or pars.d['PROBS']==pars.d['COLUMNS']:
    print("This would delete the .columns file!")
    sys.exit()    

#Assign the intrinsin rms
if pars.d['SPECTRA']=='CWWSB.list':
    print('Setting the intrinsic rms to 0.067(1+z)')
    pars.d['MIN_RMS']=0.067

pars.d['MIN_RMS']=float(pars.d['MIN_RMS'])
pars.d['MIN_MAGERR']=float(pars.d['MIN_MAGERR'])
if pars.d['INTERACTIVE']=='no': interactive=0
else: interactive=1
if pars.d['VERBOSE']=='yes': 
    print("Current parameters")
    view_keys(pars.d)
pars.d['N_PEAKS']=int(pars.d['N_PEAKS'])
if pars.d["ADD_SPEC_PROB"]!=None:
    specprob=1
    specfile=pars.d["ADD_SPEC_PROB"]
    spec=get_2Darray(specfile)
    ns=spec.shape[1]
    if ns/2!=(ns/2.):
        print("Number of columns in SPEC_PROB is odd")
        sys.exit()
    z_spec=spec[:,:ns/2]
    p_spec=spec[:,ns/2:]
    # Write output file header
    header="#ID "
    header+=ns/2*" z_spec%i"
    header+=ns/2*" p_spec%i"
    header+="\n"
    header=header % tuple(list(range(ns/2))+list(range(ns/2)))
    specout=open(specfile.split()[0]+".p_spec","w")
    specout.write(header)
else:
    specprob=0
pars.d['DELTA_M_0']=float(pars.d['DELTA_M_0'])

#sampling
if pars.d['SAMPLING'] == 'no': save_sample = False
else: save_sample = True
    
if pars.d['Z_MEAN'] == 'no': save_mean = False
else: save_mean = True
    
if pars.d['Z_SIG'] == 'no': save_std = False
else: save_std = True

if save_sample: nsamples = int(pars.d['NSAMPLES'])

#Some misc. initialization info useful for the .columns file
#nofilters=['M_0','OTHER','ID','Z_S','X','Y']
nofilters=['M_0','OTHER','ID','Z_S']

#Numerical codes for nondetection, etc. in the photometric catalog
unobs=-99. #Objects not observed
undet= 99.  #Objects not detected


#Define the z-grid
zmin=float(pars.d['ZMIN'])
zmax=float(pars.d['ZMAX'])
if zmin > zmax : raise 'zmin < zmax !'
dz=float(pars.d['DZ'])

linear=1
if linear:
    z=arange(zmin,zmax+dz,dz)
else:
    if zmax!=0.:
        zi=zmin
        z=[]
        while zi<=zmax:
            z.append(zi)	    
            zi=zi+dz*(1.+zi)
        z=array(z)
    else: z=array([0.])

#Now check the contents of the FILTERS,SED and A diBrectories

#Get the filters in stock
filters_db=[]
filters_db=glob.glob(get_fil_file('*.res'))
for i in range(len(filters_db)):
    filters_db[i]=os.path.basename(filters_db[i])
    filters_db[i]=filters_db[i][:-4]
    
#Get the SEDs in stock
sed_db=[]
sed_db=glob.glob(get_sed_file('*.sed'))
for i in range(len(sed_db)):
    sed_db[i]=os.path.basename(sed_db[i])
    sed_db[i]=sed_db[i][:-4]

#Get the ABflux files in stock
ab_db=[]
ab_db=glob.glob(get_ab_file('*.AB'))
for i in range(len(ab_db)):
    ab_db[i]=os.path.basename(ab_db[i])
    ab_db[i]=ab_db[i][:-3]

#Get a list with the filter names and check whether they are in stock
col_file=pars.d['COLUMNS']
filters=get_str(col_file,0)

for cosa in nofilters: 
    if filters.count(cosa):filters.remove(cosa)
    
if pars.d['EXCLUDE']!='none':
    if type(pars.d['EXCLUDE'])==type(' '):
        pars.d['EXCLUDE']=[pars.d['EXCLUDE']]
    for cosa in pars.d['EXCLUDE']:
        if filters.count(cosa):filters.remove(cosa)

for filter in filters:
    if filter[-4:]=='.res': filter=filter[:-4]
    if filter not in filters_db:
        print("FILTER", filters_db, filter)
        print('filter ', filter, 'not in database at',get_fil_file(''), ':')
        if ask('Print filters in database?'):
            for line in filters_db: print(line)
        sys.exit()

#Get a list with the spectrum names and check whether they're in stock
#Look for the list in the home directory first, 
#if it's not there, look in the SED directory
spectra_file=os.path.join(homedir,pars.d['SPECTRA'])
if not os.path.exists(spectra_file):

    spectra_file=get_sed_file(pars.d['SPECTRA'])

spectra=get_str(spectra_file,0)
for i in range(len(spectra)):
    if spectra[i][-4:]=='.sed': spectra[i]=spectra[i][:-4]

nf=len(filters)
nt=len(spectra)
nz=len(z)

#Get the model fluxes
f_mod=zeros((nz,nt,nf))*0.
abfiles=[]

for it in range(nt):
    for jf in range(nf):
        if filters[jf][-4:]=='.res': filtro=filters[jf][:-4]
        else: filtro=filters[jf]
        model=spectra[it]+'.'+filtro+'.AB'
        #print("MODEL", model)
        model_path = get_ab_file(model)
        abfiles.append(model)
        #Generate new ABflux files if not present
        # or if new_ab flag on
        if pars.d['NEW_AB']=='yes' or model[:-3] not in ab_db:
            if spectra[it] not in sed_db:
                print('SED ', spectra[it], 'not in database at',get_sed_file(''))
                #		for line in sed_db:
                #                    print line
                sys.exit()
            #print spectra[it],filters[jf]
            print('     Generating ',model,'....')
            ABflux(spectra[it],filtro,madau=pars.d['MADAU'])
            #z_ab=arange(0.,zmax_ab,dz_ab) #zmax_ab and dz_ab are def. in bpz_tools
            # abflux=f_z_sed(spectra[it],filters[jf], z_ab,units='nu',madau=pars.d['MADAU'])
            # abflux=clip(abflux,0.,1e400)
            # buffer=join(['#',spectra[it],filters[jf], 'AB','\n'])
            #for i in range(len(z_ab)):
            #	 buffer=buffer+join([`z_ab[i]`,`abflux[i]`,'\n'])
            #open(model_path,'w').write(buffer)
            #zo=z_ab
            #f_mod_0=abflux
        #else:
            #Read the data

        zo,f_mod_0=get_data(model_path,(0,1))
	#Rebin the data to the required redshift resolution
        f_mod[:,it,jf]=match_resol(zo,f_mod_0,z)
        #if sometrue(less(f_mod[:,it,jf],0.)):
        if less(f_mod[:,it,jf],0.).any():
            print('Warning: some values of the model AB fluxes are <0')
            print('due to the interpolation ')
            print('Clipping them to f>=0 values')
            #To avoid rounding errors in the calculation of the likelihood
            f_mod[:,it,jf]=clip(f_mod[:,it,jf],0.,1e300)

            #We forbid f_mod to take values in the (0,1e-100) interval
            #f_mod[:,it,jf]=where(less(f_mod[:,it,jf],1e-100)*greater(f_mod[:,it,jf],0.),0.,f_mod[:,it,jf])
            


#Here goes the interpolacion between the colors
ninterp=int(pars.d['INTERP'])

ntypes = pars.d['NTYPES']
if ntypes == None:
    nt0 = nt
else:
    nt0 = list(ntypes)
    for i, nt1 in enumerate(nt0):
        print(i, nt1)
        nt0[i] = int(nt1)
    if (len(nt0) != 3) or (sum(nt0) != nt):
        print()
        print('%d ellipticals + %d spirals + %d ellipticals' % tuple(nt0))
        print('does not add up to %d templates' % nt)
        print('USAGE: -NTYPES nell,nsp,nsb')
        print('nell = # of elliptical templates')
        print('nsp  = # of spiral templates')
        print('nsb  = # of starburst templates')
        print('These must add up to the number of templates in the SPECTRA list')
        print('Quitting BPZ.')
        sys.exit()

if ninterp:
    nti=nt+(nt-1)*ninterp
    buffer=zeros((nz,nti,nf))*1.
    tipos=arange(0.,float(nti),float(ninterp)+1.)
    xtipos=arange(float(nti))
    for iz in arange(nz):
        for jf in range(nf):
            buffer[iz,:,jf]=match_resol(tipos,f_mod[iz,:,jf],xtipos)
    nt=nti
    f_mod=buffer

#for j in range(nf):
#    plot=FramedPlot()
#    for i in range(nt): plot.add(Curve(z,log(f_mod[:,i,j]+1e-40)))
#    plot.show()
#    ask('More?')

#Load all the parameters in the columns file to a dictionary   
col_pars=params()
col_pars.fromfile(col_file)

# Read which filters are in which columns
flux_cols=[]
eflux_cols=[]
cals=[]
zp_errors=[]
zp_offsets=[]
for filter in filters:
    datos=col_pars.d[filter]
####WILL'S WAY DOESN"T OFFSET INDECES
#    flux_cols.append(datos[0])
#    eflux_cols.append(datos[1])
    flux_cols.append(datos[0])
    eflux_cols.append(datos[1])
    cals.append(datos[2])
    zp_errors.append(datos[3])
    zp_offsets.append(datos[4])
zp_offsets=array(list(map(float,zp_offsets)))
if pars.d['ZP_OFFSETS']:
    zp_offsets+=array(list(map(float,pars.d['ZP_OFFSETS'])))

flux_cols=tuple(flux_cols)
eflux_cols=tuple(eflux_cols)
#print(eflux_cols)

#READ the flux and errors from obs_file
###WILLS VERSION!!!
##f_obs=get_2Darray_fromfits(obs_file,flux_cols)
##ef_obs=get_2Darray_fromfits(obs_file,eflux_cols)

f_obs=get_2Darray_hdf5(obs_file,flux_cols)
print('\n!!!!\nF_OBS: ', f_obs, f_obs.shape)
ef_obs=get_2Darray_hdf5(obs_file,eflux_cols)
print('\n!!!!!\n EF_OBS', ef_obs, ef_obs.shape)
#REMOVE THESE and replace with hdf5-SJS March 6, 2019
#f_obs=get_2Darray(obs_file,flux_cols)
#ef_obs=get_2Darray(obs_file,eflux_cols)
####
#print(ef_obs[0])
#f_obs=get_2Darray(obs_file,flux_cols)
#ef_obs=get_2Darray(obs_file,eflux_cols)

#convert to 'AB' fluxes - how can this possibly be necessary!? Looks like it is. WHY?
#Nope, things are still mostly bull! dmag are waaay off, or is that flux? that would be unhelpful....

#Trying out if this works better with BDF fluxes, otherwise get uninformative likelihoods - Raul and Alex
flux_conv_factor = (10**((48.6 - pars.d['FLUX_ZP'])/2.5))
f_obs /= flux_conv_factor
ef_obs /= flux_conv_factor

#Convert them to arbitrary fluxes if they are in magnitudes
print('pars.d[\'MAG\']:', pars.d['MAG'])
if pars.d['MAG']=='yes':
    seen=greater(f_obs,0.)*less(f_obs,undet)
    no_seen=equal(f_obs,undet)
    no_observed=equal(f_obs,unobs)
    todo=seen+no_seen+no_observed
    #The minimum photometric error is 0.01
    #ef_obs=ef_obs+seen*equal(ef_obs,0.)*0.001
    ef_obs=where(greater_equal(ef_obs,0.),clip(ef_obs,pars.d['MIN_MAGERR'],1e10),ef_obs)
    if add.reduce(add.reduce(todo))!=todo.shape[0]*todo.shape[1]:
        print('Objects with unexpected magnitudes!')
        print("""Allowed values for magnitudes are 
        0<m<"""+repr(undet)+" m="+repr(undet)+"(non detection), m="+repr(unobs)+"(not observed)") 
        for i in range(len(todo)):
            if not alltrue(todo[i,:]):
                print(i+1,f_obs[i,:],ef_obs[i,:])
        sys.exit()
 
    #Detected objects
    try:
        f_obs=where(seen,10.**(-.4*f_obs),f_obs)
    except OverflowError:
        print('Some of the input magnitudes have values which are >700 or <-700')
        print('Purge the input photometric catalog')
        print('Minimum value',min(f_obs))
        print('Maximum value',max(f_obs))
        print('Indexes for minimum values',argmin(f_obs,0.))
        print('Indexes for maximum values',argmax(f_obs,0.))
        print('Bye.')
        sys.exit()

    try:
        ef_obs=where(seen,(10.**(.4*ef_obs)-1.)*f_obs,ef_obs)
    except OverflowError:
        print('Some of the input magnitude errors have values which are >700 or <-700')
        print('Purge the input photometric catalog')
        print('Minimum value',min(ef_obs))
        print('Maximum value',max(ef_obs))
        print('Indexes for minimum values',argmin(ef_obs,0.))
        print('Indexes for maximum values',argmax(ef_obs,0.))
        print('Bye.')
        sys.exit()

    #print 'ef', ef_obs[0,:nf]
    #print 'f',  f_obs[1,:nf]
    #print 'ef', ef_obs[1,:nf]

    #Looked at, but not detected objects (mag=99.)
    #We take the flux equal to zero, and the error in the flux equal to the 1-sigma detection error.
    #If m=99, the corresponding error magnitude column in supposed to be dm=m_1sigma, to avoid errors
    #with the sign we take the absolute value of dm 
    f_obs=where(no_seen,0.,f_obs)
    ef_obs=where(no_seen,10.**(-.4*abs(ef_obs)),ef_obs)

    #Objects not looked at (mag=-99.)
    f_obs=where(no_observed,0.,f_obs)
    ef_obs=where(no_observed,0.,ef_obs)


#Flux codes:
# If f>0 and ef>0 : normal objects
# If f==0 and ef>0 :object not detected
# If f==0 and ef==0: object not observed
#Everything else will crash the program

#Check that the observed error fluxes are reasonable
#if sometrue(less(ef_obs,0.)): raise 'Negative input flux errors'
if less(ef_obs,0.).any(): raise 'Negative input flux errors'

f_obs=where(less(f_obs,0.),0.,f_obs) #Put non-detections to 0
ef_obs=where(less(f_obs,0.),maximum(1e-100,f_obs+ef_obs),ef_obs) # Error equivalent to 1 sigma upper limit

#if sometrue(less(f_obs,0.)) : raise 'Negative input fluxes'
seen=greater(f_obs,0.)*greater(ef_obs,0.)
no_seen=equal(f_obs,0.)*greater(ef_obs,0.)
no_observed=equal(f_obs,0.)*equal(ef_obs,0.)

todo=seen+no_seen+no_observed
if add.reduce(add.reduce(todo))!=todo.shape[0]*todo.shape[1]:
    print('Objects with unexpected fluxes/errors')

#Convert (internally) objects with zero flux and zero error(non observed)
#to objects with almost infinite (~1e108) error and still zero flux
#This will yield reasonable likelihoods (flat ones) for these objects
ef_obs=where(no_observed,1e108,ef_obs)

#Include the zero point errors
zp_errors=array(list(map(float,zp_errors)))
zp_frac=e_mag2frac(zp_errors)
#zp_frac=10.**(.4*zp_errors)-1.
ef_obs=where(seen,sqrt(ef_obs*ef_obs+(zp_frac*f_obs)**2),ef_obs)
ef_obs=where(no_seen,sqrt(ef_obs*ef_obs+(zp_frac*(ef_obs/2.))**2),ef_obs)

#Add the zero-points offset
#The offsets are defined as m_new-m_old
zp_offsets=array(list(map(float,zp_offsets)))
zp_offsets=where(not_equal(zp_offsets,0.),10.**(-.4*zp_offsets),1.)
f_obs=f_obs*zp_offsets
ef_obs=ef_obs*zp_offsets

#Convert fluxes to AB if needed
for i in range(f_obs.shape[1]):
    if cals[i]=='Vega':
        const=mag2flux(VegatoAB(0.,filters[i]))
        f_obs[:,i]=f_obs[:,i]*const
        ef_obs[:,i]=ef_obs[:,i]*const
    elif cals[i]=='AB':continue
    else:
        print('AB or Vega?. Check '+col_file+' file')
        sys.exit()
		
#Get m_0 (if present)
if 'M_0' in col_pars.d:
    m_0_col=col_pars.d['M_0']
    print ("m0column name:  %s"%(m_0_col))
    #take out old way, put in hdf5 way    
    #m_0_col=int(col_pars.d['M_0'])-1
    #m_0=get_data(obs_file,m_0_col)
    m_0=get_2Darray_hdf5(obs_file,m_0_col)
    print(col_pars.d['M_0'])
###WILL'S m_0!
###    m_0=get_2Darray_fromfits(obs_file,tuple([col_pars.d['M_0'],]))
    #print(m_0[0])
###WILL'S ADDITION OF FLUX_ZP!!  TAKE OUT FOR NOW
###    if pars.d['MAG']=='no':
###        m_0 = pars.d['FLUX_ZP']-2.5*log10(m_0)
    print((m_0[0]))
    m_0+=pars.d['DELTA_M_0'] # this only makes sense if m_0 is in mag - so assume this and convert.

#Get the objects ID (as a string)
if 'ID' in col_pars.d:
    #print col_pars.d['ID']
    id_col=col_pars.d['ID']
    #TAKE out old way, put in hdf5 Mar 6 2019 SJS
    #id_col=int(col_pars.d['ID'])-1
    #id=get_str(obs_file,id_col)
    id = get_2Darray_hdf5(obs_file,id_col)
####WILL'S METHOD FROM FITS!
####    id=get_long_fromfits(obs_file,col=col_pars.d['ID'])
    #id=get_str_fromfits(obs_file,id_col)
else:
    id=list(map(str,list(range(1,len(f_obs[:,0])+1))))

#Get spectroscopic redshifts (if present)
if 'Z_S' in col_pars.d:
    z_s_col=col_pars.d['Z_S']
    #TAKE out old way, switch to HDF5
    #z_s_col=int(col_pars.d['Z_S'])-1
    #z_s=get_data(obs_file,z_s_col)
    z_s=get_2Darray_hdf5(obs_file,z_s_col)

###WILL'S METHOD WITH FITS
###    z_s=get_2Darray_fromfits(obs_file,tuple([col_pars.d['Z_S'],]))
    #z_s=get_data(obs_file,z_s_col)

#Get the X,Y coordinates
if 'X' in col_pars.d:
    datos = col_pars.d['X']
    if len(datos) == 1:  # OTHERWISE IT'S A FILTER!
        x_col=int(col_pars.d['X'])-1
        x=get_data(obs_file,x_col)
if 'Y' in col_pars.d:
    datos = col_pars.d['Y']
    if len(datos) == 1:  # OTHERWISE IT'S A FILTER!
        y_col=int(datos)-1
        y=get_data(obs_file,y_col)

#If 'check' on, initialize some variables
check=pars.d['CHECK']

# This generates a file with m,z,T and observed/expected colors
#if check=='yes': pars.d['FLUX_COMPARISON']=root+'.flux_comparison'

checkSED = check!='no'

if pars.d['OUTPUT_CUT'] is not "Null":
    output_cut = float(pars.d['OUTPUT_CUT'])
    cutmask = (m_0 < output_cut)
    f_obs = f_obs[cutmask]
    ef_obs = ef_obs[cutmask]
    m_0 = m_0[cutmask]
    z_s = z_s[cutmask]
    id = id[cutmask]
    if 'X' in col_pars.d:
        x = x[cutmask]
    if 'Y' in col_pars.d:
        y = y[cutmask]

ng=f_obs.shape[0]
print ("final length of trimmed dataset: %d"%ng)
if checkSED:
    # PHOTOMETRIC CALIBRATION CHECK
    #r=zeros((ng,nf),float)+1.
    #dm=zeros((ng,nf),float)+1.
    #w=r*0.
    # Defaults: r=1, dm=1, w=0
    frat = ones((ng,nf), float)
    dmag = ones((ng,nf), float)
    fw  = zeros((ng,nf), float)

#Visualize the colors of the galaxies and the templates 

#When there are spectroscopic redshifts available
if interactive and 'Z_S' in col_pars.d and plots and checkSED and ask('Plot colors vs spectroscopic redshifts?'):
    color_m=zeros((nz,nt,nf-1))*1.
    if plots == 'pylab':
        figure(1)
    nrows=2
    ncols=(nf-1)/nrows
    if (nf-1)%nrows: ncols+=1
    for i in range(nf-1):
	##plot=FramedPlot()
	# Check for overflows
        fmu=f_obs[:,i+1]
        fml=f_obs[:,i]
        good=greater(fml,1e-100)*greater(fmu,1e-100)
        zz,fmu,fml=multicompress(good,(z_s,fmu,fml))
        colour=fmu/fml
        colour=clip(colour,1e-5,1e5)
        colour=2.5*log10(colour)
        if plots == 'pylab':
            subplot(nrows,ncols,i+1)
            plot(zz,colour,"bo")
        elif plots == 'biggles':
            d=Points(zz,colour,color='blue')
            plot.add(d)
        for it in range(nt):
            #Prevent overflows
            fmu=f_mod[:,it,i+1]
            fml=f_mod[:,it,i]
            good=greater(fml,1e-100)
            zz,fmu,fml=multicompress(good,(z,fmu,fml))
            colour=fmu/fml
            colour=clip(colour,1e-5,1e5)
            colour=2.5*log10(colour)
            if plots == 'pylab':
                plot(zz,colour,"r")
            elif plots == 'biggles':
                d=Curve(zz,colour,color='red')    
                plot.add(d)
        if plots == 'pylab':
            xlabel(r'$z$')
            ylabel('%s - %s' %(filters[i],filters[i+1]))
        elif plots == 'biggles':
            plot.xlabel=r'$z$'
            plot.ylabel='%s - %s' %(filters[i],filters[i+1])
            plot.save_as_eps('%s-%s.eps'%(filters[i],filters[i+1]))
            plot.show()
    if plots == 'pylab':
        show()
        inp = input('Hit Enter to continue.')

#Get other information which will go in the output file (as strings)
if 'OTHER' in col_pars.d:
    if col_pars.d['OTHER']!='all':
        other_cols=col_pars.d['OTHER']
        if type(other_cols)==type((2,)):
            other_cols=tuple(map(int,other_cols))
        else:
            other_cols=(int(other_cols),)
        other_cols=[x-1 for x in other_cols]
        n_other=len(other_cols)
    else:
        n_other=get_2Darray(obs_file,cols='all',nrows=1).shape[1]
        other_cols=list(range(n_other))

    others=get_str(obs_file,other_cols)

    if len(other_cols)>1:
        other=[]
        for j in range(len(others[0])):
            lista=[]
            for i in range(len(others)):
                lista.append(others[i][j])
            other.append(" ".join(lista))
    else:
        other=others


if pars.d['GET_Z']=='no': get_z=0
else: get_z=1

#Prepare the output file
out_name=pars.d['OUTPUT']
if get_z:
    if os.path.exists(out_name):
        os.system('cp %s %s.bak' % (out_name,out_name))
        print("File %s exists. Copying it to %s.bak" % (out_name,out_name))
    #output=open(out_name,'w')
    output = h5py.File(out_name,"w")
if pars.d['PROBS_LITE']=='no': save_probs=0
else: save_probs=1

if pars.d['PROBS']=='no': save_full_probs=0
else: save_full_probs=1

if pars.d['PROBS2']=='no': save_probs2=0
else: save_probs2=1

#Include some header information

#   File name and the date...
time_stamp=time.ctime(time.time())
#if get_z: output.write('## File '+out_name+'  '+time_stamp+'\n')
timestamp = str(time.asctime())
#if get_z: timeoutput = output.create_dataset("PARAMS/time",(1,),maxshape=(1,),dtype=dt,data = timestamp)
if get_z: output.attrs["TIMESTAMP"] = timestamp

#and also the parameters used to run bpz...
#if get_z:output.write("""##
##Parameters used to run BPZ:
##
#""")
claves=list(pars.d.keys())
claves.sort()
for key in claves:
    if type(pars.d[key])==type((1,)):
        cosa=str.join(',',(list(pars.d[key])))
    else:
        cosa=str(pars.d[key])
    #if get_z: output.write('##'+key.upper()+'='+cosa+'\n')
    tmpnamex = "%s"%key.upper()
    #dt = h5py.special_dtype(vlen=str)
    #if get_z: output.create_dataset(tmpnamex,(1,),maxshape=(1,),dtype=dt,data=str(cosa))
    if get_z: output.attrs[tmpnamex] = str(cosa)

if save_full_probs:
    #Shelve some info on the run
    full_probs=shelve.open(pars.d['PROBS'])
    full_probs['TIME']=time_stamp
    full_probs['PARS']=pars.d

if save_probs:
    #probs=open(pars.d['PROBS_LITE'],'w')
    #SWITCH to HDF5 WRITE OUT!
    probs = h5py.File(pars.d['PROBS_LITE'],"w")
    #probs.write('# ID  p_bayes(z)  where z=arange(%.4f,%.4f,%.4f) \n' % (zmin,zmax+dz,dz))
    #save the zgrid!
    zgridwrite = probs.create_dataset("ZGRID",(len(z),),maxshape = (None,),dtype = 'f', data = z)
    if ng<chunksize:
        probswrite = probs.create_dataset("PDF", (ng,len(z)),dtype='f')
        idwrite = probs.create_dataset("ID",(ng,),dtype='i8')
    else:
        probswrite = probs.create_dataset("PDF", (chunksize,len(z)),maxshape = (None,len(z)),dtype='f')
        idwrite = probs.create_dataset("ID",(chunksize,),maxshape=(None,),dtype='i8')
        
if save_probs2:
    #probs2=open(pars.d['PROBS2'],'w')
    probs2=open('probs2.txt','w')
    probs2.write('# id t  z1    P(z1) P(z1+dz) P(z1+2*dz) ...  where dz = %.4f\n' % dz)
    #probs2.write('# ID\n')
    #probs2.write('# t  z1  P(z1)  P(z1+dz)  P(z1+2*dz) ...  where dz = %.4f\n' % dz)

#Use a empirical prior?
tipo_prior=pars.d['PRIOR']
useprior=0
if 'M_0' in col_pars.d: has_mags=1
else: has_mags=0
if has_mags and tipo_prior!='none' and tipo_prior!='flat': useprior=1

#Add cluster 'spikes' to the prior?
cluster_prior=0.
if pars.d['ZC'] : 
    cluster_prior=1
    if type(pars.d['ZC'])==type(""): zc=array([float(pars.d['ZC'])])
    else:    zc=array(list(map(float,pars.d['ZC'])))
    if type(pars.d['FC'])==type(""): fc=array([float(pars.d['FC'])])
    else:    fc=array(list(map(float,pars.d['FC'])))    

    fcc=add.reduce(fc)
    if fcc>1. : 
        print(ftc)
        raise 'Too many galaxies in clusters!'
    pi_c=zeros((nz,nt))*1.
    #Go over the different cluster spikes
    for i in range(len(zc)):
	#We define the cluster within dz=0.01 limits
        cluster_range=less_equal(abs(z-zc[i]),.01)*1.
        #Clip values to avoid overflow
        exponente=clip(-(z-zc[i])**2/2./(0.00333)**2,-700.,0.)
	#Outside the cluster range g is 0
        g=exp(exponente)*cluster_range
        norm=add.reduce(g)
        pi_c[:,0]=pi_c[:,0]+g/norm*fc[i]

    #Go over the different types
    print('We only apply the cluster prior to the early type galaxies')
    for i in range(1,3+2*ninterp):
        pi_c[:,i]=pi_c[:,i]+pi_c[:,0]



#Output format
format='%'+repr(maximum(5,len(str(id[0]))))+'s' #ID format
format=format+pars.d['N_PEAKS']*' %.3f %.3f  %.3f %.3f %.5f'+' %.3f %.3f %10.3f'

##Add header with variable names to the output file
#sxhdr="""##
###Column information
###
## 1 ID"""
#k=1
#
#if pars.d['N_PEAKS']>1:
#    for j in range(pars.d['N_PEAKS']):
#        sxhdr+="""
## %i Z_B_%i
## %i Z_B_MIN_%i
## %i Z_B_MAX_%i
## %i T_B_%i
## %i ODDS_%i""" % (k+1,j+1,k+2,j+1,k+3,j+1,k+4,j+1,k+5,j+1)
#        k+=5
#else:
#    sxhdr+="""
## %i Z_B
## %i Z_B_MIN
## %i Z_B_MAX
## %i T_B
## %i ODDS""" % (k+1,k+2,k+3,k+4,k+5)
#    k+=5
#    
#sxhdr+="""    
## %i Z_ML
## %i T_ML
## %i CHI-SQUARED\n""" % (k+1,k+2,k+3)
#
#nh=k+4
#if 'Z_S' in col_pars.d: 
#    sxhdr=sxhdr+'# %i Z_S\n' % nh
#    format=format+'  %.3f'
#    nh+=1
#if has_mags: 
#    format=format+'  %.3f'
#    sxhdr=sxhdr+'# %i M_0\n' % nh
#    nh+=1
#if 'OTHER' in col_pars.d:
#    sxhdr=sxhdr+'# %i OTHER\n' % nh
#    format=format+' %s'
#    nh+=n_other

#print sxhdr

#if get_z: output.write(sxhdr+'##\n')

#REPLACE output header with creation of blank datasets for each
#Check the chunksize:
if ng<chunksize:
    print ("ng smaller than chunksize, no chunking...")
    outid = output.create_dataset("ID",(ng,),dtype='i8')
    outzb = output.create_dataset("Z_B",(ng,),dtype='f')
    outzbmin = output.create_dataset("Z_B_MIN",(ng,),dtype='f')
    outzbmax = output.create_dataset("Z_B_MAX",(ng,),dtype='f')
    outtb = output.create_dataset("T_B",(ng,),dtype='f')
    outodds = output.create_dataset("ODDS",(ng,),dtype='f')
    outzml = output.create_dataset("Z_ML",(ng,),dtype='f')
    outtml = output.create_dataset("T_ML",(ng,),dtype='f')
    outchi = output.create_dataset("CHI_SQ",(ng,),dtype='f')
    if save_sample: 
        outzsamp = output.create_dataset("Z_SAMP",(ng,),dtype='f')
    if save_mean:
        outzmean = output.create_dataset("Z_MEAN", (ng,), dtype='f')
    if save_std:
        outsig = output.create_dataset("Z_SIG", (ng,), dtype='f')
    if 'Z_S' in col_pars.d: 
        outzs = output.create_dataset("Z_S",(ng,),dtype='f')
    if has_mags: 
        outmag = output.create_dataset("M_0",(ng,),dtype='f')
else:
    print ("ng larger than chunksize, creating first chunk of size %d" %chunksize)
    outid = output.create_dataset("ID",(chunksize,),maxshape=(None,),dtype='i8')
    outzb = output.create_dataset("Z_B",(chunksize,),maxshape=(None,),dtype='f')
    outzbmin = output.create_dataset("Z_B_MIN",(chunksize,),maxshape=(None,),dtype='f')
    outzbmax = output.create_dataset("Z_B_MAX",(chunksize,),maxshape=(None,),dtype='f')
    outtb = output.create_dataset("T_B",(chunksize,),maxshape=(None,),dtype='f')
    outodds = output.create_dataset("ODDS",(chunksize,),maxshape=(None,),dtype='f')
    outzml = output.create_dataset("Z_ML",(chunksize,),maxshape=(None,),dtype='f')
    outtml = output.create_dataset("T_ML",(chunksize,),maxshape=(None,),dtype='f')
    outchi = output.create_dataset("CHI_SQ",(chunksize,),maxshape=(None,),dtype='f')
    if save_sample: 
        outzsamp = output.create_dataset("Z_SAMP",(chunksize,),maxshape=(None,),dtype='f')
    if save_mean:
        outzmean = output.create_dataset("Z_MEAN", (chunksize,),maxshape=(None,), dtype='f')
    if save_std:
        outsig = output.create_dataset("Z_SIG", (chunksize,),maxshape=(None,), dtype='f')
    if 'Z_S' in col_pars.d: 
        outzs = output.create_dataset("Z_S",(chunksize,),maxshape=(None,),dtype='f')
    if has_mags: 
        outmag = output.create_dataset("M_0",(chunksize,),maxshape=(None,),dtype='f')

        
h5quantities = [outid,outzb,outzbmin,outzbmax,outtb,outodds,outzml,outtml,outchi]
if save_sample: h5quantities.append(outzsamp)
if save_mean: h5quantities.append(outzmean)
if save_std: h5quantities.append(outsig)
if 'Z_S' in col_pars.d:
    h5quantities.append(outzs)
if has_mags:
    h5quantities.append(outmag)

#LEAVE OFF "OTHER" implementation for now!
#if 'OTHER' in col_pars.d:
#    for oth_name in col_pars.d['OTHER']:
        


odds_i=float(pars.d['ODDS'])
oi=inv_gauss_int(odds_i)

print(odds_i,oi)

#Proceed to redshift estimation

if checkSED: buffer_flux_comparison=""

if pars.d['CONVOLVE_P']=='yes':
    # Will Convolve with a dz=0.03 gaussian to make probabilities smoother
    # This is necessary; if not there are too many close peaks
    sigma_g=0.03
    x=arange(-3.*sigma_g, 3.*sigma_g + dz/10., dz)  # made symmetric --DC
    gaus=exp(-(x/sigma_g)**2)

if pars.d["NMAX"]!=None: ng=int(pars.d["NMAX"])
its_samples = []
cdf_no = 0
seed = int(pars.d['SEED'])
sampling_rng = np.random.default_rng(seed)
full_chi2 = []
for ig in range(ng):
    #if ig%1000 == 0: print(ig)
    #Don't run BPZ on galaxies with have z_s > z_max
    #if col_pars.d.has_key('Z_S'):
    #    if z_s[ig]<9.9 and z_s[ig]>zmax : continue

    #add test for chunks
    if ig%chunksize==0 and ng > chunksize:
        print (ig)
        if ng-ig<chunksize:
            for item in h5quantities:
                item.resize(ng,axis=0)
            if save_probs:
                idwrite.resize(ng,axis=0)
                probswrite.resize(ng,axis=0)
        else:
            newsize = ig+chunksize
            for item in h5quantities:
                item.resize(newsize,axis=0)
            if save_probs:
                idwrite.resize(newsize,axis=0)
                probswrite.resize(newsize,axis=0)
    if not get_z: continue
    if pars.d['COLOR']=='yes': likelihood=p_c_z_t_color(f_obs[ig,:nf],ef_obs[ig,:nf],f_mod[:nz,:nt,:nf])
    else: likelihood=p_c_z_t(f_obs[ig,:nf],ef_obs[ig,:nf],f_mod[:nz,:nt,:nf])

    if 0:
        print(f_obs[ig,:nf])
        print(ef_obs[ig,:nf])
    
    iz_ml=likelihood.i_z_ml
    t_ml=likelihood.i_t_ml
    chi2 = likelihood.chi2
    red_chi2=likelihood.min_chi2/float(nf-1.)
    full_chi2.append(likelihood.chi2)
    #p=likelihood.Bayes_likelihood
    #likelihood.various_plots()
    #print 'FULL BAYESAIN LIKELIHOOD'
    p=likelihood.likelihood
    if not ig:
        print('ML * prior -- NOT QUITE BAYESIAN')

    #plo=FramedPlot()
    #for i in range(p.shape[1]):
    #    plo.add(Curve(z,likelihood.likelihood[:nz,i]/sum(sum(likelihood.likelihood[:nz,:]))))
    #    plo.add(Curve(z,likelihood.bayes_likelihood[:nz,i]/sum(sum(likelihood.bayes_likelihood[:nz,:])),color='red'))
    #    #plo.add(Curve(z,p[:nz,i]/sum(sum(p[:nz,:])),color='red'))
    #plo.show()
    #ask('More?')


    if pars.d['ONLY_TYPE']=='yes': #Use only the redshift information, no priors
        p_i=zeros((nz,nt))*1.
        j=searchsorted(z,z_s[ig])
        #print j,nt,z_s[ig]
        p_i[j,:]=1./float(nt)
    else:
        if useprior:
            if pars.d['PRIOR']=='lensing':
                p_i=prior(z,m_0[ig],tipo_prior,nt0,ninterp,x[ig],y[ig])
            else:
                p_i=prior(z,m_0[ig],tipo_prior,nt0,ninterp)
        else:
            p_i=ones((nz,nt),float)/float(nz*nt)
        if cluster_prior:p_i=(1.-fcc)*p_i+pi_c
    
    if save_full_probs: full_probs[str(id[ig])]=[z,p_i[:nz,:nt],p[:nz,:nt],red_chi2]  
    
    #Multiply the prior by the likelihood to find the final probability
    test = np.ones_like(p[:nz,:nt])
    test /= np.sum(test)
    test *= np.sum(p[:nz,:nt])
    #print('TEST, LIKELIHOOD sums', np.sum(test), np.sum(p[:nz,:nt]))
    assert not np.allclose(p[:nz,:nt], test)
    pb=p_i[:nz,:nt]*p[:nz,:nt]
    pb_f_name = str(id[ig])+'.prob_2d'
    #savez(pb_f_name, pb=pb, chi2=p, prior=p_i)

    #plo=FramedPlot()
    #for i in range(p.shape[1]):
    #    plo.add(Curve(z,p_i[:nz,i]/sum(sum(p_i[:nz,:]))))
    #for i in range(p.shape[1]):
    #    plo.add(Curve(z,p[:nz,i]/sum(sum(p[:nz,:])),color='red'))
    #plo.add(Curve(z,pb[:nz,-1]/sum(pb[:nz,-1]),color='blue'))
    #plo.show()
    #ask('More?')

    
    #Convolve with a gaussian of width \sigma(1+z) to take into
    #accout the intrinsic scatter in the redshift estimation 0.06*(1+z)
    #(to be done)

    #Estimate the bayesian quantities
    p_bayes=add.reduce(pb[:nz,:nt],-1)
    #print("HERE PB ", pb[:nz,:nt].shape, '\n', pb[:nz,:nt])
    #print("P_BAYES ", p_bayes.shape, '\n', p_bayes)
    #print p_bayes.shape
    #print argmax(p_bayes)
    #print p_bayes[300:310]

    #Convolve with a gaussian
    if pars.d['CONVOLVE_P']=='yes' and pars.d['ONLY_TYPE']=='no': 
        #print 'GAUSS CONV'
        p_bayes=convolve(p_bayes,gaus,1)    
        #print 'gaus', gaus
        #print p_bayes.shape
        #print argmax(p_bayes)
        #print p_bayes[300:310]
        

    # Eliminate all low level features in the prob. distribution
    pmax=max(p_bayes)
    p_bayes=where(greater(p_bayes,pmax*float(pars.d['P_MIN'])),p_bayes,0.)
    
    norm=add.reduce(p_bayes)
    p_bayes=p_bayes/norm

    if specprob:
        p_spec[ig,:]=match_resol(z,p_bayes,z_spec[ig,:])*p_spec[ig,:]
        norma=add.reduce(p_spec[ig,:])
        if norma==0.: norma=1.
        p_spec[ig,:]/=norma
        #vyjod=tuple([id[ig]]+list(z_spec[ig,:])+list(p_spec[ig,:])+[z_s[ig],
        #                int(float(other[ig]))])
        vyjod=tuple([id[ig]]+list(z_spec[ig,:])+list(p_spec[ig,:]))
        formato="%s "+5*" %.4f"
        formato+=5*" %.3f"
        #formato+="  %4f %i"
        formato+="\n"
        print(formato % vyjod)
        specout.write(formato % vyjod)        
    
    if pars.d['N_PEAKS']>1:
        # Identify  maxima and minima in the final probability
        g_max=less(p_bayes[2:],p_bayes[1:-1])*less(p_bayes[:-2],p_bayes[1:-1])
        g_min=greater(p_bayes[2:],p_bayes[1:-1])*greater(p_bayes[:-2],p_bayes[1:-1])
    
        g_min+=equal(p_bayes[1:-1],0.)*greater(p_bayes[2:],0.)
        g_min+=equal(p_bayes[1:-1],0.)*greater(p_bayes[:-2],0.)
    
        i_max=compress(g_max,arange(nz-2))+1
        i_min=compress(g_min,arange(nz-2))+1                      

        # Check that the first point and the last one are not minima or maxima,
        # if they are, add them to the index arrays

        if p_bayes[0]>p_bayes[1]:
            i_max=concatenate([[0],i_max])
            i_min=concatenate([[0],i_min])
        if p_bayes[-1]>p_bayes[-2]:
            i_max=concatenate([i_max,[nz-1]])
            i_min=concatenate([i_min,[nz-1]])
        if p_bayes[0]<p_bayes[1]:
            i_min=concatenate([[0],i_min])
        if p_bayes[-1]<p_bayes[-2]:
            i_min=concatenate([i_min,[nz-1]])


        p_max=take(p_bayes,i_max)
        #p_min=take(p_bayes,i_min)
        p_tot=[]
        z_peaks=[]
        t_peaks=[]
        # Sort them by probability values
        p_max,i_max=multisort(1./p_max,(p_max,i_max))
        # For each maximum, define the minima which sandwich it
        # Assign minima to each maximum
        jm=searchsorted(i_min,i_max)
        p_max=list(p_max)

        for i in range(len(i_max)):
            z_peaks.append([z[i_max[i]],z[i_min[jm[i]-1]],z[i_min[jm[i]]]])
            t_peaks.append(argmax(pb[i_max[i],:nt]))
            p_tot.append(sum(p_bayes[i_min[jm[i]-1]:i_min[jm[i]]]))
            # print z_peaks[-1][0],f_mod[i_max[i],t_peaks[-1]-1,:nf]

        if ninterp:
            t_peaks=list(array(t_peaks)/(1.+ninterp))
            
        if pars.d['MERGE_PEAKS']=='yes':
            # Merge peaks which are very close 0.03(1+z)
            merged=[]
            for k in range(len(z_peaks)):
                for j in range(len(z_peaks)):
                    if j>k and k not in merged and j not in merged:
                        if abs(z_peaks[k][0]-z_peaks[j][0])<0.06*(1.+z_peaks[j][0]):
                            # Modify the element which receives the accretion
                            z_peaks[k][1]=minimum(z_peaks[k][1],z_peaks[j][1])
                            z_peaks[k][2]=maximum(z_peaks[k][2],z_peaks[j][2])
                            p_tot[k]+=p_tot[j]
                            # Put the merged element in the list
                            merged.append(j)
                            
            #print merged
            # Clean up
            copia=p_tot[:]
            for j in merged:
                p_tot.remove(copia[j])
            copia=z_peaks[:]
            for j in merged:
                z_peaks.remove(copia[j])
            copia=t_peaks[:]
            for j in merged:
                t_peaks.remove(copia[j])                
            copia=p_max[:]
            for j in merged:
                p_max.remove(copia[j])                

        if sum(array(p_tot))!=1.:
            p_tot=array(p_tot)/sum(array(p_tot))
            
    # Define the peak
    iz_b=argmax(p_bayes)
    zb=z[iz_b]
    # OKAY, NOW THAT GAUSSIAN CONVOLUTION BUG IS FIXED
    # if pars.d['ONLY_TYPE']=='yes': zb=zb-dz/2. #This corrects a small bias
    # else: zb=zb-dz #This corrects another small bias --DC

    #Integrate within a ~ oi*sigma interval to estimate 
    # the odds. (based on a sigma=pars.d['MIN_RMS']*(1+z))
    #Look for the number of sigma corresponding 
    #to the odds_i confidence limit

    zo1=zb-oi*pars.d['MIN_RMS']*(1.+zb)
    zo2=zb+oi*pars.d['MIN_RMS']*(1.+zb)
    if pars.d['Z_THR']>0:
        zo1=float(pars.d['Z_THR'])
        zo2=float(pars.d['ZMAX'])
    o=odds(p_bayes[:nz],z,zo1,zo2)

    # Integrate within the same odds interval to find the type
    # izo1=maximum(0,searchsorted(z,zo1)-1)
    # izo2=minimum(nz,searchsorted(z,zo2))
    # t_b=argmax(add.reduce(p[izo1:izo2,:nt],0))

    it_b=argmax(pb[iz_b,:nt])
    t_b = it_b + 1
    
    if ninterp: 
        tt_b=float(it_b)/(1.+ninterp)
        tt_ml=float(t_ml)/(1.+ninterp)
    else:
        tt_b=it_b
        tt_ml=t_ml
        
    if max(pb[iz_b,:]) < 1e-300:
        print('NO CLEAR BEST t_b; ALL PROBABILITIES ZERO')
        t_b = -1.
        tt_b = -1.

    #print it_b, t_b, tt_b, pb.shape
    
    if 0:
        print(f_mod[iz_b,it_b,:nf])
        
        print(min(ravel(p_i)), max(ravel(p_i)))
        print(min(ravel(p)), max(ravel(p)))
        print(p_i[iz_b,:])
        print(p[iz_b,:])
        print(p_i[iz_b, it_b])  # prior
        print(p[iz_b, it_b])    # chisq
        print(likelihood.likelihood[iz_b, it_b])
        print(likelihood.chi2[iz_b, it_b])
        print(likelihood.ftt[iz_b, it_b])
        print(likelihood.foo)
        
        print()
        print('t_b', t_b)
        print('iz_b', iz_b)
        print('nt', nt)
        print(max(ravel(pb)))
        impb = argmax(ravel(pb))
        impbz = impb / nt
        impbt = impb % nt
        print(impb, impbz, impbt)
        print(ravel(pb)[impb])
        print(pb.shape, (nz, nt))
        print(pb[impbz,impbt])
        print(pb[iz_b, it_b])
        print('z, t', z[impbz], t_b)
        print(t_b)

    # Redshift confidence limits
    z1,z2=interval(p_bayes[:nz],z,odds_i)
    if pars.d['PHOTO_ERRORS']=='no':
        zo1=zb-oi*pars.d['MIN_RMS']*(1.+zb)
        zo2=zb+oi*pars.d['MIN_RMS']*(1.+zb)
        if zo1<z1: z1=maximum(0.,zo1)
        if zo2>z2: z2=zo2

    # Print output

    if pars.d['N_PEAKS']==1:
        salida=[id[ig],zb,z1,z2,tt_b+1,o,z[iz_ml],tt_ml+1,red_chi2]
    else:
        salida=[id[ig]]
        for k in range(pars.d['N_PEAKS']):
            if k<= len(p_tot)-1:
                salida=salida+list(z_peaks[k])+[t_peaks[k]+1,p_tot[k]]
            else:
                salida+=[-1.,-1.,-1.,-1.,-1.]
        salida+=[z[iz_ml],tt_ml+1,red_chi2]
        
    if 'Z_S' in col_pars.d:salida.append(z_s[ig])
    if has_mags: salida.append(m_0[ig]-pars.d['DELTA_M_0'])
    if 'OTHER' in col_pars.d:salida.append(other[ig])

    #if get_z: output.write(format % tuple(salida)+'\n')
    if get_z:
        outid[ig] = id[ig]
        outzb[ig] = zb
        outzbmin[ig] = z1
        outzbmax[ig] = z2
        outtb[ig] = tt_b+1
        outodds[ig]=o
        outzml[ig] = z[iz_ml]
        outtml[ig] = tt_ml+1
        outchi[ig] = red_chi2
        if 'Z_S' in col_pars.d:
            outzs[ig] = z_s[ig]
        if has_mags:
            outmag[ig]=(m_0[ig]-pars.d['DELTA_M_0'])

        #if ig<ng-1:
        #    cat_size = outid.size
        #    new_size = cat_size+1
        #    outid.resize(new_size,axis=0)
        #    outzb.resize(new_size,axis=0)
        #    outzbmin.resize(new_size,axis=0)
        #    outzbmax.resize(new_size,axis=0)
        #    outtb.resize(new_size,axis=0)
        #    outodds.resize(new_size,axis=0)
        #    outzml.resize(new_size,axis=0)
        #    outtml.resize(new_size,axis=0)
#       #     outchi.resize(new_size,axis=0)
        #    if 'Z_S' in col_pars.d:
        #        outzs.resize(new_size,axis=0)
        #    if has_mags:
        #        outmag.resize(new_size,axis=0)
                
    #if pars.d['VERBOSE']=='yes': print(format % tuple(salida))


    #try:
    #    if sometrue(greater(z_peaks,7.5)):
    #        connect(z,p_bayes)
    #        ask('More?')        
    #except:
    #    pass

    odd_check=odds_i
 
    if checkSED:
        ft=f_mod[iz_b,it_b,:]
        fo=f_obs[ig,:]
        efo=ef_obs[ig,:]
        dfosq = ((ft - fo) / efo) ** 2
        if 0:  
            print(ft)
            print(fo)
            print(efo)
            print(dfosq)
            pause()
        factor=ft/efo/efo
        ftt=add.reduce(ft*factor)
        fot=add.reduce(fo*factor)
        am=fot/ftt
        ft=ft*am   
        if 0:
            print(factor)
            print(ftt)
            print(fot)
            print(am)
            print(ft)
            print()
            pause()

        flux_comparison=[id[ig],m_0[ig],z[iz_b],t_b,am]+list(concatenate([ft,fo,efo]))
        nfc=len(flux_comparison)

        format_fc='%s  %.2f  %.2f   %i'+(nfc-4)*'   %.3e'+'\n'
        buffer_flux_comparison=buffer_flux_comparison+ format_fc % tuple(flux_comparison)
        if o>=odd_check:
            # PHOTOMETRIC CALIBRATION CHECK
            # Calculate flux ratios, but only for objects with ODDS >= odd_check 
            #  (odd_check = 0.95 by default)
            # otherwise, leave weight w = 0 by default
            eps = 1e-10
            frat[ig,:] = divsafe(fo, ft, inf=eps, nan=eps)
            #fw[ig,:] = greater(fo, 0)
            fw[ig,:] = divsafe(fo, efo, inf=1e8, nan=0)
            fw[ig,:] = clip(fw[ig,:], 0, 100)
            #print fw[ig,:]
            #print
            
        if 0:
            bad=less_equal(ft,0.)	
            #Avoid overflow by setting r to 0.
            fo=where(bad,0.,fo)
            ft=where(bad,1.,ft)
            r[ig,:]=fo/ft
            try:
                dm[ig,:]=-flux2mag(fo/ft)
            except:
                dm[ig,:]=-100
            # Clip ratio between 0.01 & 100
            r[ig,:]=where(greater(r[ig,:],100.),100.,r[ig,:])
            r[ig,:]=where(less_equal(r[ig,:],0.),0.01,r[ig,:])
            #Weight by flux
            w[ig,:]=where(greater(fo,0.),1,0.)
	    #w[ig,:]=where(greater(fo,0.),fo,0.)
            #print fo
            #print r[ig,:]
            #print
            # This is no good becasue r is always > 0 (has been clipped that way)
	    #w[ig,:]=where(greater(r[ig,:],0.),fo,0.)
            # The is bad because it would include non-detections:
	    #w[ig,:]=where(greater(r[ig,:],0.),1.,0.)
	    
    if save_probs:
        #texto='%s ' % str(id[ig])
        #texto+= len(p_bayes)*'%.3e '+'\n'
        #probs.write(texto % tuple(p_bayes))
        idwrite[ig] = np.int(id[ig])
        probswrite[ig] = p_bayes
        
        #if ig<ng-1: 
        #    xsize = idwrite.size + 1
        #    idwrite.resize(xsize,axis=0)
        #    probswrite.resize(xsize,axis=0)
            
        
    # pb[z,t] -> p_bayes[z]
    # 1. tb are summed over
    # 2. convolved with Gaussian if CONVOLVE_P
    # 3. Clipped above P_MIN * max(P), where P_MIN = 0.01 by default
    # 4. normalized such that sum(P(z)) = 1
    if save_probs2:  # P = exp(-chisq / 2)
        #probs2.write('%s\n' % id[ig])
        pmin = pmax * float(pars.d['P_MIN'])
        #pb = where(less(pb,pmin), 0, pb)
        chisq = -2 * log(pb)
        for itb in range(nt):
            chisqtb = chisq[:,itb]
            pqual = greater(pb[:,itb], pmin)
            chisqlists = seglist(chisqtb, pqual)
            if len(chisqlists) == 0:
                continue
            #print pb[:,itb]
            #print chisqlists
            zz = arange(zmin, zmax+dz, dz)
            zlists = seglist(zz, pqual)
            for i in range(len(zlists)):
                probs2.write('%s  %2d  %.3f  ' % (id[ig], itb+1, zlists[i][0]))
                fmt = len(chisqlists[i]) * '%4.2f '+'\n'
                probs2.write(fmt % tuple(chisqlists[i]))
            #fmt = len(chisqtb) * '%4.2f '+'\n'
            #probs2.write('%d  ' % itb)
            #probs2.write(fmt % tuple(chisqtb))

    if save_sample:
        #pdf = p_bayes #np.sum(p[:nz,:nt], axis=1) #[:,t_ml] # modify this to be sum of templates
        samps = np.random.choice(z, p=p_bayes, size=nsamples)
#         samplemask = pdf>1.e-14
#         pdf = pdf[samplemask]
#         cdf = np.cumsum(pdf)# don't need to divide, p_bayes is already normalized/np.sum(pdf)
#         #print("NORM", np.sum(pdf), cdf.max())
#         samplemasksum=samplemask.sum()
#         if samplemasksum>10: # see if we really want 10 here
#             ITS = interp1d(cdf, z[samplemask], kind='linear')
#             rnumber = sampling_rng.uniform(cdf[0], cdf[-1], size=nsamples)
#             samps = ITS(rnumber)
#         else:
#             samps=-1000-samplemasksum
        #its_samples.append(samps)
        outzsamp[ig] = samps
        outzmean[ig] = np.average(z, weights=p_bayes)
        outsig[ig] = np.sqrt( np.average( (z-outzmean[ig])**2, weights=p_bayes) )
        #gt3 = samps>3.505
        #lt0 = samps<0.
        #if ig>2890:
        #    print(cdf)
        #if np.any(np.logical_or(gt3, lt0)):
            #print('BAD SAMPS', samps)
            #cdf_no+=1
            #np.savetxt(root+f'_CDF#{cdf_no}.txt', np.array([z[samplemask], cdf]).T, fmt='%.18e')
            #np.savetxt(root+f'_badsample#{cdf_no}.txt', np.array([samps, rnumber]).T, fmt='%.18e')

    #if ig == 34:
    #if (0.4 < zb < .8) & (21 < m_0[ig] < 22):
        #breakpoint()
        
if save_sample:
    print('out_name', out_name)
    #print('save sample was set to TRUE')
    #np.savetxt(out_name.split('.')[0]+'_ITS.txt', its_samples)
    
#print("ROOT", root)
#    with open(root+'_ITS.txt', "w") as output:
#        for sample in its_samples:
#            output.write('%s/n' % sample)
        
#if checkSED: open(pars.d['FLUX_COMPARISON'],'w').write(buffer_flux_comparison)
if write_flux_comp: open(pars.d['CHECK'],'w').write(buffer_flux_comparison)

#This remains unchanged for h5py
if get_z: output.close()

#if checkSED and get_z:
if checkSED:
    #try:
    if 1:
        if interactive:
            print("")
            print("")
            print("PHOTOMETRIC CALIBRATION TESTS")
            # See PHOTOMETRIC CALIBRATION CHECK above
            #ratios=add.reduce(w*r,0)/add.reduce(w,0)
            #print "Average, weighted by flux ratios f_obs/f_model for objects with odds >= %g" % odd_check
            #print len(filters)*'  %s' % tuple(filters)
            #print  nf*' % 7.3f       ' % tuple(ratios)
            #print "Corresponding zero point shifts"
            #print  nf*' % 7.3f       ' % tuple(-flux2mag(ratios))
            #print
            
            fratavg = sum(fw*frat, axis=0) / sum(fw, axis=0)
            dmavg = -flux2mag(fratavg)
            fnobj = sum(greater(fw,0), axis=0)
            #print 'fratavg', fratavg
            #print 'dmavg', dmavg
            #print 'fnobj', fnobj
            #fnobj = sum(greater(w[:,i],0))
            print("If the dmag are large, add them to the .columns file (zp_offset), then re-run BPZ.")
            print("(For better results, first re-run with -ONLY_TYPE yes to fit SEDs to known spec-z.)")
            print()
            print('  fo/ft    dmag   nobj   filter')
            #print nf
            for i in range(nf):
                print('% 7.3f  % 7.3f %5d   %s'\
                    % (fratavg[i], dmavg[i], fnobj[i], filters[i]))
                    #% (ratios[i], -flux2mag(ratios)[i], sum(greater(w[:,i],0)), filters[i])
            #print '  fo/ft    dmag    filter'
            #for i in range(nf):
            #    print '% 7.3f  % 7.3f   %s'  % (ratios[i], -flux2mag(ratios)[i], filters[i])
            print("fo/ft = Average f_obs/f_model weighted by f_obs/ef_obs for objects with ODDS >= %g" % odd_check)
            print("dmag = magnitude offset which should be applied (added) to the photometry (zp_offset)")
            print("nobj = # of galaxies considered in that filter (detected and high ODDS >= %g)" % odd_check)
            # print r
            # print w
            #print
            #print "Number of galaxies considered (with ODDS >= %g):" % odd_check
            #print '  ', sum(greater(w,0)) / float(nf)
            #print '(Note a galaxy detected in only 5 / 6 filters counts as 5/6 = 0.833)'
            #print sum(greater(w,0))
            
            #This part is experimental and may not work in the general case
            #print "Median color offsets for objects with odds > "+`odd_check`+" (not weighted)"
            #print len(filters)*'  %s' % tuple(filters)
            #r=flux2mag(r)
            #print  nf*' %.3f       ' % tuple(-median(r))
            #print  nf*' %.3f       ' % tuple(median(dm))
            #rms=[]
            #efobs=[]

            #for j in range(nf):
            #    ee=where(greater(f_obs[:,j],0.),f_obs[:,j],2.)
            #    zz=e_frac2mag(ef_obs[:,j]/ee)
            #    
            #    xer=arange(0.,1.,.02)
            #    hr=hist(abs(r[:,j]),xer)
            #    hee=hist(zz,xer)
            #    rms.append(std_log(compress(less_equal(r[:,j],1.),r[:,j])))
            #    zz=compress(less_equal(zz,1.),zz)
            #    efobs.append(sqrt(mean(zz*zz)))
                
            #print  nf*' %.3f       ' % tuple(rms)
            #print  nf*' %.3f       ' % tuple(efobs) 
            #print  nf*' %.3f       ' % tuple(sqrt(abs(array(rms)**2-array(efobs)**2)))

    #except: pass

    if save_full_probs: full_probs.close()
    #if save_probs: probs.close()
    if save_probs: probs.close()
    if save_probs2: probs2.close()
#np.save(root+'.chi2.npy', full_chi2)
    
#what format do we want to save it as? HDF5, shelve, fits, csv?
    
if plots and checkSED:
    zb,zm,zb1,zb2,o,tb=get_data(out_name,(1,6,2,3,5,4))
    #Plot the comparison between z_spec and z_B

    if 'Z_S' in col_pars.d:
        if not interactive or ask('Compare z_B vs z_spec?'):
            good=less(z_s,9.99)
            print('Total initial number of objects with spectroscopic redshifts= ',sum(good))
            od_th=0.
            if ask('Select for galaxy characteristics?\n'):
                od_th=eval(input('Odds threshold?\n'))
                good*=greater_equal(o,od_th)
                t_min=eval(input('Minimum spectral type\n'))
                t_max=eval(input('Maximum spectral type\n'))
                good*=less_equal(tb,t_max)*greater_equal(tb,t_min)
                if has_mags:
                    mg_min=eval(input('Bright magnitude limit?\n'))
                    mg_max=eval(input('Faint magnitude limit?\n'))
                    good=good*less_equal(m_0,mg_max)*greater_equal(m_0,mg_min)
                        
            zmo,zso,zbo,zb1o,zb2o,tb=multicompress(good,(zm,z_s,zb,zb1,zb2,tb))
            print('Number of objects with odds > %.2f= %i '%(od_th,len(zbo)))
            deltaz=(zso-zbo)/(1.+zso)
            sz=stat_robust(deltaz,3.,3)
            sz.run()
            outliers=greater_equal(abs(deltaz),3.*sz.rms)
            print('Number of outliers [dz >%.2f*(1+z)]=%i' % (3.*sz.rms,add.reduce(outliers)))
            catastrophic=greater_equal(deltaz*(1.+zso),1.)
            n_catast=sum(catastrophic)
            print('Number of catastrophic outliers [dz >1]=',n_catast)            
            print('Delta z/(1+z) = %.4f +- %.4f' % (sz.median,sz.rms))
            if interactive and plots:
                if plots == 'pylab':
                    figure(2)
                    subplot(211)
                    plot(arange(min(zso),max(zso)+0.01,0.01),
                         arange(min(zso),max(zso)+0.01,0.01),
                         "r")
                    errorbar(zso,zbo,[abs(zbo-zb1o),abs(zb2o-zbo)],fmt="bo")
                    xlabel(r'$z_{spec}$')
                    ylabel(r'$z_{bpz}$')
                    subplot(212)
                    plot(zso,zmo,"go",zso,zso,"r")
                    xlabel(r'$z_{spec}$')
                    ylabel(r'$z_{ML}$')
                    show()
                elif plots == 'biggles':
                    plot=FramedPlot()
                    if len(zso)>2000: symbol='dot'
                    else: symbol='circle'
                    plot.add(Points(zso,zbo,symboltype=symbol,color='blue'))
                    plot.add(Curve(zso,zso,linewidth=2.,color='red'))
                    plot.add(ErrorBarsY(zso,zb1o,zb2o))
                    plot.xlabel=r'$z_{spec}$'
                    plot.ylabel=r'$z_{bpz}$'
                    #	    plot.xrange=0.,1.5
                    #	    plot.yrange=0.,1.5
                    plot.show()
                    #
                    plot_ml=FramedPlot()
                    if len(zso)>2000: symbol='dot'
                    else: symbol='circle'
                    plot_ml.add(Points(zso,zmo,symboltype=symbol,color='blue'))
                    plot_ml.add(Curve(zso,zso,linewidth=2.,color='red'))
                    plot_ml.xlabel=r"$z_{spec}$"
                    plot_ml.ylabel=r"$z_{ML}$"
                    plot_ml.show()

    if interactive and plots and ask('Plot Bayesian photo-z histogram?'):
        if plots == 'biggles':
            dz=eval(input('Redshift interval?\n'))
            od_th=eval(input('Odds threshold?\n'))
            good=greater_equal(o,od_th)
            if has_mags:
                mg_min=eval(input('Bright magnitude limit?\n'))
                mg_max=eval(input('Faint magnitude limit?\n'))
                good=good*less_equal(m_0,mg_max)*greater_equal(m_0,mg_min)
            z=compress(good,zb)
            xz=arange(zmin,zmax,dz)
            hz=hist(z,xz)
            plot=FramedPlot()
            h=Histogram(hz,0.,dz,color='blue')
            plot.add(h)
            plot.xlabel=r'$z_{bpz}$'
            plot.ylabel=r'$N(z_{bpz})$'
            plot.show()
            if ask('Want to save plot as eps file?'):
                file=input('File name?\n')
                if file[-2:]!='ps': file=file+'.eps'	
                plot.save_as_eps(file)
    
    if interactive and plots and ask('Compare colors with photometric redshifts?'):
        if plots == 'biggles':
            color_m=zeros((nz,nt,nf-1))*1.
            for i in range(nf-1):
                plot=FramedPlot()
                # Check for overflows
                fmu=f_obs[:,i+1]
                fml=f_obs[:,i]
                good=greater(fml,1e-100)*greater(fmu,1e-100)
                zz,fmu,fml=multicompress(good,(zb,fmu,fml))
                colour=fmu/fml
                colour=clip(colour,1e-5,1e5)
                colour=2.5*log10(colour)
                d=Points(zz,colour,color='blue')
                plot.add(d)
                for it in range(nt):
                #Prevent overflows
                    fmu=f_mod[:,it,i+1]
                    fml=f_mod[:,it,i]
                    good=greater(fml,1e-100)
                    zz,fmu,fml=multicompress(good,(z,fmu,fml))
                    colour=fmu/fml
                    colour=clip(colour,1e-5,1e5)
                    colour=2.5*log10(colour)
                    d=Curve(zz,colour,color='red')    
                    plot.add(d)
                plot.xlabel=r'$z$'
                plot.ylabel='%s - %s' %(filters[i],filters[i+1])
                plot.save_as_eps('%s-%s.eps'%(filters[i],filters[i+1]))
                plot.show()

rolex.check()


