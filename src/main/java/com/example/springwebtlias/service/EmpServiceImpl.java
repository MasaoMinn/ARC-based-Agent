package com.example.springwebtlias.service;

import com.example.springwebtlias.mapper.EmpMapper;
import com.example.springwebtlias.pojo.Emp;
import com.example.springwebtlias.pojo.PageBean;
import com.github.pagehelper.Page;
import com.github.pagehelper.PageHelper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class EmpServiceImpl implements EmpService {
    @Autowired
    private EmpMapper empMapper;
    @Override
    public PageBean selectByPage(Integer page, Integer pageSize,String name, Short gender, LocalDateTime begin, LocalDateTime end) {

//        long count = empMapper.getCount();
//        Integer start = (page - 1) * pageSize;
         PageHelper.startPage(page, pageSize);
        List<Emp> emps =  empMapper.getList(name,gender,begin,end);
        Page<Emp> p = (Page<Emp>) emps;
        PageBean pageBean = new PageBean(p.getTotal(),p.getResult());
        return pageBean;
    }

    @Override
    public void delete(List<Integer> ids) {
        empMapper.delete(ids);
        return;
    }

    @Override
    public void save(Emp emp) {
        emp.setCreateTime(LocalDateTime.now());
        emp.setUpdateTime(LocalDateTime.now());
        empMapper.save(emp);
        return;
    }
}
