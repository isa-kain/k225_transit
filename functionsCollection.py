#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Thu Jun 15 09:49:10 2017

@author: X-phile
"""
import batman
import numpy as np
import math
import matplotlib.pyplot as plt
import emcee
import corner
import re
import copy
#from os import sys
import time as timepackage
from zachopy import oned as bin
#from plotwalkers import walkers
import pickle
#import sklearn.preprocessing as pre

global dataset
global reduction

# Kipping 2012
# https://academic.oup.com/mnras/article/435/3/2152/1024138/Efficient-uninformative-sampling-of-limb-darkening#18186712
# Eqs 15-18
def calc_u1u2(q1, q2):
	u1 = 2.*np.sqrt(q1)*q2
	u2 = np.sqrt(q1)*(1.-2.*q2)
	return u1, u2

def calc_q1q2(u1, u2):
	q1 = (u1 + u2)**2.
	q2 = u1/( 2*(u1+u2) )
	return q1, q2

# Eastman ??
def calc_eccw(sec, ses):
    ecc = sec**2. + ses**2.
    w = np.arctan2(ses, sec)
    return ecc, np.rad2deg(w)

def calc_escw(ecc, w):
    sec = np.sqrt(ecc)*np.cos(np.deg2rad(w))
    ses = np.sqrt(ecc)*np.sin(np.deg2rad(w))
    return sec, ses

# Dawson & Johnson
# requires very long term to be added to log likelihood
def calc_g(ecc, w):
    return 1.+ecc*np.sin(np.deg2rad(w))/np.sqrt(1.-ecc**2)


def find_key(key):
    if 'Megastack' in key:
        with open('megaslope_file.txt', 'r') as slope_file:
            if re.search(key, slope_file.read()):
                return True
            else:
                return False
    elif 'mearth' in key:
        with open('mearth_slope_file.txt', 'r') as slope_file:
            key = key.split('_')[0] + '.0;'
            if re.search(key, slope_file.read()):
                return True
            else:
                return False
    elif 'spitzer' in key:
        with open('spitzer_slope_file.txt', 'r') as slope_file:
            key = key.split('_')[0] + '.0;'
            if re.search(key, slope_file.read()):
                return True
            else:
                return False
    elif 'LCO' in key:
        with open('LCO_slope_file.txt', 'r') as slope_file:
            key = key.split('_')[0] + '.0;'
            if re.search(key, slope_file.read()):
                return True
            else:
                return False
    elif 'K2' in key:
        if 'k2sc' in reduction:
            with open('K2_k2sc_slope_file.txt', 'r') as slope_file:
                key = key.split('_')[0] + '.0;'
                if re.search(key, slope_file.read()):
                    return True
                else:
                    return False
        elif 'ktwo' in reduction:
            with open('K2_ktwo_slope_file.txt', 'r') as slope_file:
                key = key.split('_')[0] + '.0;'
                if re.search(key, slope_file.read()):
                    return True
                else:
                    return False


def lnprior(theta, minmax, a_mean=25.33, a_sigma=0.36, rp_mean=0.10844, rp_sigma=0.01): #rp_sig = 2*0.00047
    assert len(theta) == len(minmax)
    for i in range(len(theta)):
        if (theta[i] < minmax[i][0]) or (theta[i] > minmax[i][1]): # a parameter is out of range
            return -np.inf

    ## Gaussian prior on a/R*, rp
    lnprior_a = - (1.0/2.0)*((theta[1]-a_mean)/a_sigma)**2.0

    lnprior_r = - (1.0/2.0)*((theta[0]-rp_mean)/rp_sigma)**2.0

    ## Don't let the planet go inside the star
    ecc, w = calc_eccw(theta[3],theta[4])
    if (theta[1]*(1.-ecc) < 1):
        return -np.inf

    ## ecc must be 0 to 1
    if (w < -180.) or (w > 180.):
        return -np.inf
    if (ecc < 0) or (ecc > 1):
        return -np.inf

    return lnprior_r + lnprior_a

def lnlikelihood(theta, params, model, t, flux, err, myt0): #flux = adjusted magnitude, err = adjusted magError
    ## Initialize batman
    params.rp = copy.deepcopy(theta[0])
    params.a = copy.deepcopy(theta[1])
    params.t0 = copy.deepcopy(theta[2])
    ecc, w = calc_eccw(theta[3], theta[4])
    params.ecc = copy.deepcopy(ecc)
    params.w = copy.deepcopy(w)

    u1, u2 = calc_u1u2(theta[5], theta[6])
    params.u = copy.deepcopy([u1, u2])
    inclination = theta[9] # impact = math.acos(theta[9]/theta[1])*180./math.pi
    params.inc = copy.deepcopy(inclination)
    ltcurve = model.light_curve(params)

    ## Calc lnlikelihood
    # drawn from http://nexsci.caltech.edu/workshop/2016/JWSTtransit_overview_document.pdf (pg 20)
    residuals = flux/(theta[7]*(t-myt0) + theta[8]) - ltcurve
    ln_likelihood = -0.5*(np.sum((residuals/err)**2 + np.log(2.0*np.pi*(err)**2)))

    if np.random.random() < 1e-4:
      print timepackage.ctime(timepackage.time()), "lnlikelihood:", ln_likelihood
      print theta
#        print params.rp, params.a

    ## Examine bad values
# ERN thinks log likeli can be negative
#    if ln_likelihood<0:
#        print 'problematic theta:', theta
#        print calc_eccw(theta[3], theta[4]) ## ecc, w
#        return -np.inf
    if not np.all(np.isfinite(residuals)):
#        print "residuals:", residuals
#        print "theta:", theta
        return -np.inf
    if not np.all(np.isfinite(err)):
#        print "errors:", err
#        print "theta:", theta
        return -np.inf

    return ln_likelihood


def lnprobability(theta, params, model, t, flux, err, variables, myt0):
    order = ['rp', 'a', 't0', 'secosw', 'sesinw', 'q1', 'q2', 'slope', 'offset', 'inc']
    theta_all = []
    range_all = []

    ## Determine which variables are being varied
    i = 0
    for p in order:
        range_all.append( [variables[p]['min'],variables[p]['max']] )
        if variables[p]['vary']:
            theta_all.append(theta[i])
            i = i+1
        else:
            theta_all.append(variables[p]['value'])

    ## Find prior, likelihood
    assert (i) == len(theta)
    lp = lnprior(theta_all, range_all)
#    print 'lp: ', lp
    if not np.isfinite(lp):
        return -np.inf
    lli = lnlikelihood(theta_all, params, model, t, flux, err, myt0)
    #print params.rp, params.a, params.t0, params.ecc, params.w, params.u, params.inc
    #print lp, lli
#    print 'lli: ', lli
    return lp + lli

##==================================================##
##==================================================##

def prelim(x, y, yerr, conv_flux=False):
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(yerr)
    time = x[m]
    magnitude = y[m]
    magError = yerr[m]

    ## If magnitude, convert to flux
    if conv_flux==True:
        print 'converting to flux'
        magnitude = np.power(10, magnitude/-2.5)
        magError = magnitude*magError/-2.5*np.log(10)

    ## Timesort, normalize flux -- THIS IS WHERE MAGERROR PROBLEM IS
    index = np.argsort(time)
    time = time[index]
    magError = magError[index]/np.median(magnitude)
    magnitude = magnitude[index]/np.median(magnitude)

    print 'y sample: ', magnitude[0:5]
    print 'yerr sample: ', magError[0:5]

    ## Find midtransit time
    t0 = 2457062.57964
    per = 3.484552     #derived 3.484564
    numtransits = np.abs(round((time[0]-t0)/per))
    myt0 = t0 + per*numtransits
    print 'myt0: ', myt0

    # Cut out-of-transit data   -- REDUCES TIME TO ZERO IF T0 EARLIER THAN TIME[0]
    ind = 0
    limit = np.ones(len(time), dtype = bool)
    for t in time:
        if 'K' in dataset:
            n = 5./24.
        else:
            n = 0.1
        if t<=(myt0-n) or t>=(myt0+n):
            limit[ind] = False
        else:
            limit[ind] = True
        ind+=1

    time = time[limit]
    magnitude = magnitude[limit]
    magError = magError[limit]

    print 'y sample: ', magnitude[0:5]
    print 'yerr sample: ', magError[0:5]

    print 'len time: ', len(time)

    ## Filter outliers
    for i in range(0,2):
        std = np.std(magnitude)
        avg = np.mean(magnitude)

        ind = 0
        check = np.ones(len(time), dtype = bool)
        if 'K' in dataset:
            num = 4
        else:
            num=3
        for m in magnitude:
            if m>=(avg + (num*std)) or m<=(avg - (num*std)):
                check[ind] = False
            else:
                check[ind] = True
            ind+=1
        time = time[check]
        magnitude = magnitude[check]
        magError = magError[check]

    print 'y sample: ', magnitude[0:5]
    print 'yerr sample: ', magError[0:5]

#    print "INPUT DATASET", x, y

    return time, magnitude, magError


##==================================================##

def initialModel(time, magnitude, magError, serial):

    ## Pparams from email from Andrew 8/10/18
    per = 3.48456236
    rp_rstar = 0.10844
    a_rstar = 25.33
    #impact = 0.676
    #inclination = math.acos(impact/a_rstar)*180./math.pi
    inclination = 88.108

    t0 = 2457062.57971 ## 2454833 + 2229.57971
    numtransits = np.abs(round((min(time)-t0)/per))
    myt0 = t0 + per*numtransits

    ## Fill in params for batman
    params = batman.TransitParams()
    params.t0 = myt0
    params.per = per
    params.rp = rp_rstar
    params.a = a_rstar
    params.inc = inclination
    params.ecc = 0.227
    params.w = 98.
    params.limb_dark = "quadratic"
    if 'S' in str(dataset):
#        params.u = [0.313, 0.154]  ##GJ 1132
        params.u = [0.066, 0.201]
    elif 'M' in str(dataset):
#        params.u = [0.215, 0.407]  ##GJ 1132
        params.u = [0.233, 0.304]
    else:
        params.u = [0.1, 0.3]

    ## Initialize batman
    if 'K' in dataset:
        thismodel = batman.TransitModel(params, time, supersample_factor = 7, exp_time = 0.0208)
        make_bins = False
    else:
        thismodel = batman.TransitModel(params, time)
        make_bins = True
    flux = thismodel.light_curve(params)

    ## Bin data
    if make_bins:
        bt, by, bye = bin.binto(x=((time-myt0)*24), y=magnitude, yuncertainty=magError, binwidth=.01)
        print 'binning data, 1', len(time), len(bt)
        binned = True
    else:
        binned = False

    ## Plot initial fit
    plt.figure()
    if binned:
        plt.errorbar(bt, by, bye, fmt='o', c='k', alpha=.4)
    else:
        plt.errorbar((time-myt0)*24, magnitude, magError, fmt='o', c='k', alpha=.4)
    plt.plot((time-myt0)*24, flux, c='r', alpha = .7, linewidth=3, zorder = 10)
    plt.xlabel('Time from mid-transit in hours')
    plt.ylabel('Flux relative to baseline')
    if 'Megastack' in str(serial):
        plt.title('Initial fit of stacked transits')
    else:
        plt.title('Initial fit of ' + str(serial.split('_')[1]) + ' transit ' + str(serial.split('_')[0]))
    if 'K' in dataset:
        title = str(serial) + '_' + str(reduction) + '.pdf'
    else:
        title = str(serial) + '.pdf'
    print title
    plt.savefig('../plots/' + title)
#    plt.show()
    plt.close()

    return rp_rstar, a_rstar, myt0, params, time, magnitude, magError, thismodel, numtransits

##==================================================##

def emceeModel(rp_rstar, a_rstar, myt0, params, time, magnitude, magError, thismodel, serial, transit_num):

    ## Open parameter files
    mearth_slope_file = open('mearth_slope_file.txt', 'a+')
    megaslope_file = open('megaslope_file.txt', 'a+')
    spitzer_slope_file = open('spitzer_slope_file.txt', 'a+')
    LCO_slope_file = open('LCO_slope_file.txt', 'a+')
    if 'k2sc' in reduction:
        K2_slope_file = open('K2_k2sc_slope_file.txt', 'a+')
    elif 'ktwo' in reduction:
        K2_slope_file = open('K2_ktwo_slope_file.txt', 'a+')

    ## Create dictionary of parameters
    oneparam = {'texname':'', 'vary': True, 'value':1.,
            'scale': 1., 'min':0., 'max':1.,
            'best': [np.nan, np.nan, np.nan]}
    variables = {'rp': copy.deepcopy(oneparam), 'a': copy.deepcopy(oneparam), 't0': copy.deepcopy(oneparam),
             'secosw': copy.deepcopy(oneparam), 'sesinw': copy.deepcopy(oneparam),
             'q1': copy.deepcopy(oneparam), 'q2': copy.deepcopy(oneparam),
             'slope': copy.deepcopy(oneparam), 'offset': copy.deepcopy(oneparam), 'inc': copy.deepcopy(oneparam)}

    guess_secosw, guess_sesinw  = calc_escw(params.ecc, params.w)
    guess_q1, guess_q2 = calc_q1q2(params.u[0], params.u[1])

    ## Set values, bounds for each parameter; determine if each will vary
    p = 'rp'
    variables[p]['texname'] = r'$rp$'
    variables[p]['value'] = params.rp
    variables[p]['vary'] = False
    variables[p]['scale'] = 5.e-4
    variables[p]['min'] = 0.
    variables[p]['max'] = 1.

    p = 'a'
    variables[p]['texname'] = r'$a$'
    variables[p]['value'] = params.a
    variables[p]['vary'] = False
    variables[p]['scale'] = 0.36
    variables[p]['min'] = 1.
    variables[p]['max'] = 30.

    p = 't0'
    variables[p]['texname'] = r'$t0$'
    variables[p]['value'] = myt0
    variables[p]['vary'] = True
    variables[p]['scale'] = 2.e-4
    variables[p]['min'] = 2456000.
    variables[p]['max'] = 2458000.

    p = 'secosw'
    variables[p]['texname'] = r'$secosw$'
    variables[p]['value'] = guess_secosw # -0.06 # -0.42082681735021493
    variables[p]['vary'] = False
    variables[p]['scale'] = 0.1
    variables[p]['min'] = -1.
    variables[p]['max'] = 1.

    p = 'sesinw'
    variables[p]['texname'] = r'$sesinw$'
    variables[p]['value'] = guess_sesinw # 0.347 #0.0023165374683225028
    variables[p]['vary'] = False
    variables[p]['scale'] = 0.4
    variables[p]['min'] = -1.
    variables[p]['max'] = 1.

    p = 'q1'
    variables[p]['texname'] = r'$q1$'
    variables[p]['value'] = guess_q1
    variables[p]['vary'] = False
    variables[p]['scale'] = 0.05
    variables[p]['min'] = 0.
    variables[p]['max'] = 1.

    p = 'q2'
    variables[p]['texname'] = r'$q2$'
    variables[p]['value'] = guess_q2
    variables[p]['vary'] = False
    variables[p]['scale'] = 0.05
    variables[p]['min'] = 0.
    variables[p]['max'] = 1.

    p = 'slope'
    variables[p]['texname'] = r'$slope$'
    variables[p]['value'] = 0.
    variables[p]['vary'] = True
    variables[p]['scale'] = 1.e-3
    variables[p]['min'] = -5.
    variables[p]['max'] = 5.

    p = 'offset'
    variables[p]['texname'] = r'$offset$'
    variables[p]['value'] = 1.
    variables[p]['vary'] = True
    variables[p]['scale'] = 1.e-3
    variables[p]['min'] = -5.
    variables[p]['max'] = 5.

    p = 'inc'
    variables[p]['texname'] = r'$i$'
    variables[p]['value'] = params.inc #math.cos(params.inc*math.pi/180.)*params.a
    variables[p]['vary'] = False
    variables[p]['scale'] = 1.e-1
    variables[p]['min'] = 0.
    variables[p]['max'] = 90.

    ## Establish order & names of parameters:
    param_order = ['rp', 'a', 't0', 'secosw', 'sesinw', 'q1', 'q2', 'slope', 'offset', 'inc']

    ## Determine which parameters are being varied
    varyparams = [] # list of parameters that are being varied this run
    theta, scale, mins, maxs = [], [], [], [] # to be filled with parameter values

    for p in param_order: # record if this parameter is being varied
        if variables[p]['vary']:
            varyparams.append(p)
            theta.append(variables[p]['value'])
            scale.append(variables[p]['scale'])  ## how are we deciding scale?
            mins.append(variables[p]['min'])
            maxs.append(variables[p]['max'])
        else: # if parameter fixed, just record the starting value as the best value
            variables[p]['best'][0] = variables[p]['value']

#    print "Varying: ", varyparams
#    for p in variables.keys():
#        print p, variables[p]['value']

    ## Number of walkers, dimensions
    ndimensions = len(varyparams)
    nwalkers = 30

    ## Determine starting positions
    np.random.seed(42)
    pos = [theta + scale*np.random.randn(ndimensions) for i in range (nwalkers)]

    ## Replace each u with q
    for p in pos:
        q1, q2 = calc_q1q2(params.u[0]+1.e-3*np.random.randn(), params.u[1]+1.e-3*np.random.randn())
        p[varyparams=='q1']=q1
        p[varyparams=='q2']=q2

    ## Determine starting positions for secosw, sesinw based on ecc and w values
    if ('secosw' in varyparams) and ('sesinw' in varyparams):
        e = np.random.uniform(low=0., high=0.6)
        w = np.random.uniform(low=0., high=180.)
        sec, ses = calc_escw(e, w)
        p[varyparams=='secosw']=sec
        p[varyparams=='sesinw']=ses

    ## Set number of steps and burn-in
    if 'S' in dataset or 'M' in dataset or 'L' in dataset:
        numsteps = 10000
        burnin = 8000
    if 'K' in dataset:
        numsteps = 5000
        burnin = 1000

    #------------------------------#
    # Run the MCMC chain
    #------------------------------#
    sampler = emcee.EnsembleSampler(nwalkers, ndimensions, lnprobability,
                                    args = (params, thismodel, time, magnitude, magError, variables, myt0))

    print "Starting MC", timepackage.ctime(timepackage.time())
    sampler.run_mcmc(pos, numsteps)  ##changed from pos_to_vary
    print "Finishing MC", timepackage.ctime(timepackage.time())

    #------------------------------#
    # Analyze results from MCMC
    #------------------------------#

    ## Remove the "burn-in" and calculate the best values
    samples = sampler.chain[:, burnin:, :].reshape((-1, ndimensions)) #8000
    best = map(lambda v: [v[1], v[2]-v[1], v[1]-v[0]], \
                       zip(*np.nanpercentile(samples, [16, 50, 84], axis=0))) ## arranged: [50th, upper error, lower error]

    print best

    ## Pickle sampler
    filename = 'pickle_' + str(serial) + '_' + str(reduction)
    sfile = open(filename, 'w+')
    pickle.dump(samples, sfile)
    sfile.close()
    print 'pickled'


    ## Update variables with best value
    i = 0
    for p in param_order:
        print p
        if variables[p]['vary']:
            variables[p]['best'] = best[i]
            i = i+1
            print p, variables[p]['best']

    assert (i) == len(theta)

    ## Calculate secondary best-fit parameters
    durations = []
    depths = []
    eccs = []
    omegas = []
    samp = {'rp':np.nan, 'a':np.nan, 't0':np.nan, 'secosw':np.nan, 'sesinw':np.nan, 'q1':np.nan, 'q2':np.nan, 'slope':np.nan, 'offset':np.nan, 'inc':np.nan}
    for i in samples:
        j = 0
        for p in param_order:
            if variables[p]['vary']:
                samp[p] = i[j]
                j+=1
            else:
                samp[p] = variables[p]['value']
        ecc, w = calc_eccw(samp['secosw'], samp['sesinw'])
#        inc = math.acos(samp['inc']/samp['a']) ##apparently these aren't single values?
        inc = np.deg2rad(samp['inc'])

        eccs.append(ecc)
        omegas.append(w)

        if ((1+samp['rp'])**2)>=(samp['a']*math.cos(inc)):
            if inc>=-math.pi/2 and inc<=math.pi/2 and inc!=0:
                # Calculating transit duration
                p1 = (1+samp['rp'])**2-(samp['a']*math.cos(inc))
                p2 = math.sin(inc)
                p3 = math.sqrt(p1)
                d1 = p3/p2

        d2 = math.asin((1/samp['a'])*(d1))
        dur = (params.per/math.pi)*d2*(math.sqrt(1-ecc**2)/(1+samp['sesinw']))
        durations.append(dur)

        ## Calculating transit depth
        dep = samp['rp']**2
        depths.append(dep)

    ## Listing best durations
    temp = np.percentile(durations, [16, 50, 84], axis=0)    ## arranged: [lower error, 50th, upper error]
    best_duration = [temp[1], temp[2]-temp[1], temp[1]-temp[0]]
    best_duration = str(best_duration)
    best_duration = '[' + best_duration[1:-1] + ']'
#    best_duration = '0'

    ## Listing best depths
    temp = np.percentile(depths, [16, 50, 84], axis=0)
    best_depth = [temp[1], temp[2]-temp[1], temp[1]-temp[0]]
    best_depth = str(best_depth)
    best_depth = '[' + best_depth[1:-1] + ']'

    ## Listing best eccentricities
    temp = np.percentile(eccs, [16, 50, 84], axis=0)
    best_ecc = [temp[1], temp[2]-temp[1], temp[1]-temp[0]]
    best_ecc = str(best_ecc)
    best_ecc = '[' + best_ecc[1:-1] + ']'

    ## Listing best omegas
    temp = np.percentile(omegas, [16, 50, 84], axis=0)
    best_w = [temp[1], temp[2]-temp[1], temp[1]-temp[0]]
    best_w = str(best_w)
    best_w = '[' + best_w[1:-1] + ']'

    ## From posterior grab max likelihood (because median could be anywhere)
    max = sampler.flatchain[np.argmax(sampler.flatlnprobability)]


    #-----------------------------------------#
    # Write out the best fit to slope file
    #-----------------------------------------#

    split = serial.split('_')
    # 89_mearth  OR  189_spitzer  OR  Megastack_spitzer  OR  Megastack_mearth
    # alt: GJ1132_mearth  OR  282_LCO  OR  1_K2

    if 'Megastack' in str(serial):
        tag = serial
    elif 'spitzer' in split[1] or 'mearth' in split[1] or 'LCO' in split[1] or 'GJ' in split[0] or 'K2' in split[1]:
        tag = split[0]
    print tag

    thing = str(tag) + ';' + str(variables['rp']['best']) + ';' + str(variables['a']['best']) + \
                    ';' + str(variables['t0']['best']) + ';' + str(variables['secosw']['best']) + \
                    ';' + str(variables['sesinw']['best']) + ';' + str(variables['q1']['best']) + \
                    ';' + str(variables['q2']['best']) + ';' + str(variables['slope']['best']) + \
                    ';' + str(variables['offset']['best']) + ';' + best_duration + ';' + best_depth + \
                    ';' + str(variables['inc']['best']) + ';' + best_ecc + ';' + best_w + ';' + str(max) + '; \n'

    ## Write thing to file
#    print "serial:", serial
    print 'thing:', thing
    if 'Megastack' in str(serial):
#        print "found em!"
        if find_key(str(serial))==False:
            megaslope_file.write(thing)
            megaslope_file.close()
#            print 'line inserted'
    elif 'mearth' in str(serial):
#        print "found em!"
        if find_key(str(serial))==False:
            mearth_slope_file.write(thing)
            mearth_slope_file.close()
#            print 'line inserted'
    elif 'spitzer' in str(serial):
#        print "found em!"
        if find_key(str(serial))==False:
            spitzer_slope_file.write(thing)
            spitzer_slope_file.close()
#            print 'line inserted'
    elif 'LCO' in str(serial):
#        print "found em!"
        if find_key(str(serial))==False:
            LCO_slope_file.write(thing)
            LCO_slope_file.close()
#            print 'line inserted'
    elif 'K2' in str(serial):
        if find_key(str(serial))==False:
            K2_slope_file.write(thing)
            K2_slope_file.close()


    #--------------------#
    # Plot best fit
    #--------------------#

    for plt_version in ('normal','residuals'):  ##FIX: when normal option removed, doesn't recognize creation of ax1
        ## Initialize and plot batman fits from all theta values
        theta_best =  np.percentile(samples, 50, axis=0)
        tlin = np.linspace(myt0-0.2, myt0+0.2, 1000)

        if "K" in dataset: #sparse K2 data means tlin doesn't sample enough during transit
            lin_time = time
        else:
            lin_time = tlin

        if plt_version=='normal':
            fig, ax1 = plt.subplots()
        elif plt_version=='residuals':
            fig, (ax1, ax2) = plt.subplots(2,1, gridspec_kw = {'height_ratios':[3, 1]}, sharex=True)
            plt.subplots_adjust(hspace=.0)
        for theta in samples[np.random.randint(len(samples), size=100)]:
            lnprobability(theta, params, thismodel, time, magnitude, magError, variables, myt0)
            if "K" in dataset:
                mlin = batman.TransitModel(params, lin_time, supersample_factor = 7, exp_time = 0.0208)  #initialize model
            else:
                mlin = batman.TransitModel(params, lin_time)

            flux = mlin.light_curve(params)*(variables['slope']['best'][0]*(lin_time-myt0) + variables['offset']['best'][0])   ###time[0]
            ax1.plot((lin_time-myt0)*24, flux, c='slateblue', linewidth=3, alpha=0.05, zorder=2)

        ## Initialize and plot batman fit from best values
        lnprobability(theta_best, params, thismodel, time, magnitude, magError, variables, myt0)
        if "K" in dataset:
            mlin = batman.TransitModel(params, lin_time, supersample_factor = 7, exp_time = 0.0208)  #initialize model
        else:
            mlin = batman.TransitModel(params, lin_time)
        newflux = mlin.light_curve(params)*(variables['slope']['best'][0]*(lin_time-myt0) + variables['offset']['best'][0])

        # compare flux calculations:
        print 'method flux: ', np.median(flux)
        print 'flux, where she be? ', np.median(newflux)

        ## Bin data
        binned = False
        if 'S' in str(dataset) or 'stacked' in serial or 'Megastack' in serial:
            bt, by, bye = bin.binto(x=time, y=magnitude, yuncertainty=magError, binwidth=.001) #binwidth=.0004
            print 'binning data, 2'
            binned = True
        if 'M' in str(dataset):
            bt, by, bye = bin.binto(x=time, y=magnitude, yuncertainty=magError, binwidth=.001)
            print 'binning data, 2'
            binned = True

        if binned:
            ax1.errorbar((bt-myt0)*24, by, bye, fmt='o', c='k', alpha=0.4, zorder = 0)
        else:
            ax1.errorbar((time-myt0)*24, magnitude, magError, fmt='o', c='k', alpha=0.4, zorder = 0)
        ax1.plot((lin_time-myt0)*24, newflux, c='purple', linewidth=2, alpha=1, zorder = 3)
        ax1.set_ylim(0.977,1.013)   #will this be constant across all datasets?

        ax1.set_xlim((time[0]-myt0)*24, (time[-1]-myt0)*24)
        ax1.set_ylabel('Relative flux (%)')
        if plt_version=='normal':
            ax1.set_xlabel('Time from mid-transit (hours)')
        elif plt_version=='residuals':
            if binned:
                if 'K' in dataset:
                    mnotlin = batman.TransitModel(params, bt, supersample_factor = 7, exp_time = 0.0208)
                else:
                    mnotlin = batman.TransitModel(params, bt)
                model_magnitude = mnotlin.light_curve(params)*(variables['slope']['best'][0]*(bt-myt0) + variables['offset']['best'][0])
                ax2.errorbar((bt-myt0)*24, by-model_magnitude, bye, fmt='o', c='k', alpha=0.4, zorder = 0)
                ax2.plot([-5,5],[0,0], c='purple', linewidth=2, alpha=1, zorder = 3)
                ax2.set_xlabel('Time from mid-transit (hours)')
                ax2.set_ylabel('Residuals (%)')
                ax2.set_ylim(-0.01,0.01)
            else:
                if 'K' in dataset:
                    mnotlin = batman.TransitModel(params, time, supersample_factor = 7, exp_time = 0.0208)
                else:
                    mnotlin = batman.TransitModel(params, time)
                model_magnitude = mnotlin.light_curve(params)*(variables['slope']['best'][0]*(time-myt0) + variables['offset']['best'][0])
                ax2.errorbar((time-myt0)*24, magnitude-model_magnitude, magError, fmt='o', c='k', alpha=0.4, zorder = 0)
                ax2.plot([-5,5],[0,0], c='purple', linewidth=2, alpha=1, zorder = 3)
                ax2.set_xlabel('Time from mid-transit (hours)')
                ax2.set_ylabel('Residuals (%)')
                ax2.set_ylim(-0.01,0.01)

        if 'Megastack' in str(serial):
            ax1.set_title('Best fit of stacked transits')
        else:
            ax1.set_title('Best fit of transit ' + str(serial))

        if 'K' in dataset or 'L' in dataset:
            if plt_version=='normal':
                title = str(serial) + '_' + str(reduction) + '_best.pdf'
            elif plt_version=='residuals':
                title = str(serial) + '_' + str(reduction) + '_best_residuals.pdf'
        else:
            if plt_version=='normal':
                title = str(serial) + '_best.pdf'
            elif plt_version=='residuals':
                title = str(serial) + '_best_residuals.pdf'
        print title

        plt.tight_layout()
        plt.savefig('../plots/'+title)
        #    plt.show()
        plt.close()

    return samples, sampler, variables

##==================================================##


def cornerPlot(samples, serial, variables):
    ## Grab a, ecc, w sample values
    param_order = ['rp', 'a', 't0', 'secosw', 'sesinw', 'q1', 'q2', 'slope', 'offset', 'inc']
    i = 0
    labels = []
    do_corner = True
    for p in param_order:
        if variables[p]['vary']:
            labels.append(variables[p]['texname'])
            if p == 'a':
                a_ind = i
            if p == 'secosw':
                c_ind = i
            if p == 'sesinw':
                s_ind = i
            i = i+1
        else:
            if p in [ 'secosw', 'sesinw']:
                do_corner = False

    ## Corner plot for a, ecc, w
    if do_corner:
        ecc = np.zeros_like(samples[:,0])
        w = np.zeros_like(samples[:,0])
        for i, sam in enumerate(samples):
            e, omega = calc_eccw(sam[c_ind], sam[s_ind])
            ecc[i] = e
            w[i] = omega

        s = np.array([samples[:,1],ecc, w]).transpose()

        plt.figure()
        corner.corner(s, labels = ['a', 'ecc', 'w'])
        title = serial + '_corner_ecc.pdf'
        plt.savefig('../plots/' + title)
        #plt.show()
        plt.close()

    plt.figure()
    corner.corner(samples, labels = labels)
    if 'K' in dataset:
        title = serial + '_' + str(reduction) + '_corner.pdf'
    else:
        title = serial + '_corner.pdf'
    #plt.show()
    plt.savefig('../plots/' + title)
    plt.close()



