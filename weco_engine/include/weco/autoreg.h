/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2018 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/

#ifndef __weco_autoreg_h__
#define __weco_autoreg_h__

#include <vector>
#include <assert.h>

namespace WeCo {

// ============================== NDAutoReg ======================

/// Auto Registration template
template<class T> class AutoReg {

public :
    static T* first() {
            return first_;
    }
    T* next() const{
            return next_;
    }

    AutoReg() : next_(first_)
        { first_ = static_cast<T*>(this);}

    static std::vector<T*> list() {
        std::vector<T*> list;
        for(T* i = first();i!=nullptr;i= i->next()) 
                list.push_back(i);
        return list;
    }

    AutoReg& operator = (const AutoReg& ) = delete;
    AutoReg& operator = (AutoReg&& ) = delete;
    AutoReg(const AutoReg& ) = delete;
    AutoReg(AutoReg&& ) = delete;


    virtual ~AutoReg() {
        for(T ** p = &first_;*p;p =&((*p)->next_)) {
            if (*p == this)  {
                *p= next_;
                break;
            }
        }
    }

private:
    T *  next_;
    static T* first_;  
};

template <class T> T* AutoReg<T>::first_ = nullptr;

// ============================== NDAutoReg ======================

/// Auto Reg With name and desc
template <class T> class NDAutoReg : public AutoReg<T> {
public:
    NDAutoReg(std::string const & name,std::string const & desc="") :
        name_(name),desc_(desc) {}

    std::string const & name() const {return name_;}
    std::string const & desc() const {return desc_;}

    static std::vector<T*> sorted_list() {
        std::vector<T*> list = T::list();
        std::sort(list.begin(),list.end(),[](T*a,T*b) {
            return a->name()<b->name();
        });
        return list;
    }
    static bool name_exists(std::string const & name) 
        {return from_name(name);}
        
    static T* from_name(std::string const & name) {
        for(T* i = T::first();i!=nullptr;i= i->next()) {
            if (i->name() == name)
                return i;
        }
        return nullptr;
    }

    static void dump_list(std::ostream & out,std::string const &header="    ") {
        for(T* i : sorted_list())
            out << header << i->name()<<" : "<<i->desc()<<std::endl;
    }

    static std::vector<std::string> name_list() {
        std::vector<std::string> res;
        for(T* i : sorted_list())
            res.emplace_back(i->name());
        return res;
    }
        


private:
    std::string const name_;
    std::string const desc_;

};

// ============================== NDAutoReg ======================


/// NDAutoReg With value
template <class T> class NDVAutoReg : public NDAutoReg<NDVAutoReg<T>> {
public :
    using BaseClass = NDAutoReg<NDVAutoReg<T>>;
    NDVAutoReg(std::string const & name, T value, std::string const & desc=""):
        BaseClass(name,desc),value_(value){}

    T value() 
        {return value_;}

    static T value_from_name(std::string const&name)
        {return BaseClass::from_name(name)->value();}
private:
    T value_;
};

}

#endif
